"""Reading the cached windows written by fetch.py. No network here."""
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "out"
PARCELS = HERE / "parcels.geojson"

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
    """{parcel_id: GeoJSON feature} from parcels.geojson (lon/lat)."""
    features = json.loads(PARCELS.read_text(encoding="utf-8"))["features"]
    return {f["properties"]["parcel_id"]: f for f in features}


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
