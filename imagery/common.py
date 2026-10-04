"""Reading the cached windows written by fetch.py. No network here."""
import json
import os
from datetime import date as Date, timedelta
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.features import rasterize
from rasterio.warp import transform_geom

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "out"
# The parcels come from the database: the API exports them to parcels.geojson before it runs the
# satellite job. Without that file (a run by hand), the seed the database is loaded from is used.
EXPORTED_PARCELS = HERE / "parcels.geojson"
SEED_PARCELS = HERE.parent / "backend" / "data" / "parcels.geojson"
PARCELS = Path(os.getenv("PARCELS_FILE") or (EXPORTED_PARCELS if EXPORTED_PARCELS.exists() else SEED_PARCELS))
# The crop calendar is the one the sensor alerts use (app.crops of sensors-alerts). The satellite reads only
# each phase's season, to know when a low or falling NDVI is normal for the crop.
CROPS_FILE = Path(os.getenv("CROPS_FILE") or HERE.parent / "sensors-alerts" / "src" / "main" / "resources" / "application.yml")

# NDVI colour ramp for looking at images: grey (water, roads) -> brown (bare soil) -> yellow -> green.
NDVI_STOPS = [
    (-0.1, (110, 110, 110)),
    (0.15, (160, 115, 75)),
    (0.35, (230, 205, 90)),
    (0.55, (140, 190, 70)),
    (0.85, (15, 95, 30)),
]


# The dates the decisions in LOGIC.md were measured on. The measure_*.py studies stay on them, so their
# numbers can still be reproduced after the rest of the season was added to the cache.
STUDY_DATES = ["2026-06-28", "2026-06-30", "2026-07-18", "2026-07-28"]


def load_index(region):
    return json.loads((CACHE / region / "scenes.json").read_text())


def study_scenes(region):
    return [s for s in load_index(region)["scenes"] if s["date"] in STUDY_DATES]


def load_parcels():
    """{parcel_id: GeoJSON feature} from the parcels file (lon/lat); parcel_id is the cadastral number."""
    features = json.loads(PARCELS.read_text(encoding="utf-8"))["features"]
    return {f["properties"]["parcel_id"]: f for f in features}


def crop_calendar():
    """{crop: {"sowing": calendar sowing day MM-DD or None, "phases": [(first day MM-DD, phase name, season), ...]}}."""
    crops = yaml.safe_load(CROPS_FILE.read_text(encoding="utf-8"))["app"]["crops"]
    return {crop: {"sowing": cfg.get("calendar-sowing"),
                   "phases": [(str(p["from"]), p["name"], p.get("season", "growing")) for p in cfg.get("phases", [])]}
            for crop, cfg in crops.items()}


MAX_SHIFT_DAYS = 60


def _sown_phases(entry, sowing_date):
    """The phases moved to the farmer's sowing date (as in sensors-alerts): N days late sowing, N days later phases.
    01-01 stays; a date further than MAX_SHIFT_DAYS from the calendar's is ignored."""
    phases = entry["phases"]
    if not entry.get("sowing") or not sowing_date:
        return phases
    sown = Date.fromisoformat(str(sowing_date))
    days = (sown - Date(sown.year, *map(int, str(entry["sowing"]).split("-")))).days
    if not days or abs(days) > MAX_SHIFT_DAYS:
        return phases

    def shift(md):
        if md == "01-01":
            return md
        d = Date(2026, *map(int, md.split("-"))) + timedelta(days=days)
        d = d if d.year == 2026 else (Date(2026, 1, 1) if days < 0 else Date(2026, 12, 31))
        return f"{d.month:02d}-{d.day:02d}"
    return sorted(((shift(p[0]), p[1], p[2]) for p in phases), key=lambda p: p[0])


def phase_on(calendar, crop, date, sowing_date=None):
    """(phase name, season) of the crop on that day (YYYY-MM-DD), moved to the parcel's sowing date if it has one;
    (None, "growing") for a crop without a calendar. Before the first phase starts, last year's last phase still runs."""
    entry = calendar.get(crop)
    phases = _sown_phases(entry, sowing_date) if entry else []
    if not phases:
        return None, "growing"
    current = phases[-1]
    for p in phases:
        if p[0] <= date[5:]:
            current = p
    return current[1], current[2]


def polygon_mask(geometry, transform, crs, shape):
    """Pixels whose centre falls inside the lon/lat polygon, on the given raster grid."""
    geom = transform_geom("EPSG:4326", crs, geometry)
    return rasterize([(geom, 1)], out_shape=shape, transform=transform, fill=0).astype(bool)


def polygon_pixels(geometry, transform, crs):
    """Outer ring of the polygon in (col, row) pixel coordinates of the grid, for drawing."""
    geom = transform_geom("EPSG:4326", crs, geometry)
    return [~transform * tuple(p) for p in geom["coordinates"][0]]


def colorize_ndvi(v, hidden=None):
    """NDVI to RGB with NDVI_STOPS; `hidden` pixels (e.g. clouds) become magenta."""
    xs = [s[0] for s in NDVI_STOPS]
    rgb = np.stack([np.interp(np.nan_to_num(v, nan=-1), xs, [s[1][k] for s in NDVI_STOPS]) for k in range(3)], -1)
    if hidden is not None:
        rgb[hidden] = (255, 0, 255)
    return rgb.astype(np.uint8)


def read_asset(region, scene, asset):
    """Array (bands, rows, cols) and its georeferencing (transform, crs)."""
    with rasterio.open(CACHE / region / scene["item_id"] / f"{asset}.tif") as ds:
        return ds.read(), ds.transform, ds.crs


def reflectance(dn, scene):
    """Surface reflectance from L2A digital numbers; DN 0 is no data and becomes NaN.

    Earth Search already removed the +1000 BOA offset when boa_offset_applied is true
    (checked on real pixels, see LOGIC.md). The -0.1 offset in the STAC raster metadata
    must not be applied on top of that.
    """
    if scene["boa_offset_applied"] is None:
        raise ValueError(f"{scene['item_id']}: boa_offset_applied missing, cannot tell the offset")
    out = dn.astype(np.float32)
    if not scene["boa_offset_applied"]:
        out -= 1000
    out /= 10000
    out[dn == 0] = np.nan
    return out


def to_10m(a20):
    """20 m band onto the 10 m grid. Windows are aligned, so each pixel becomes exactly 2x2."""
    return np.repeat(np.repeat(a20, 2, axis=-2), 2, axis=-1)


def ndvi(red, nir):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (nir - red) / (nir + red)
