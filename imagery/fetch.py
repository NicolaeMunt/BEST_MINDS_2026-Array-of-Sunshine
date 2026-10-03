"""Download Sentinel-2 L2A windows from Earth Search into cache/.

This is the only script that needs the network. A region is either the overview
area around Orhei (used to choose the demo parcel) or one parcel from a GeoJSON.
For every date it keeps one scene of tile 35TPN and saves only the window that
covers the region, one small GeoTIFF per band. Files already on disk are not
downloaded again, so a second run makes no requests at all.

For a parcel, SCL is read first. If even before the cloud mask is widened less than
MIN_VALID_PCT of the shrunken parcel is usable, the analysis would skip the scene anyway,
so its other bands are not downloaded; the scene stays listed with bands_downloaded false.

    python fetch.py --area
    python fetch.py --parcels parcels.geojson
    python fetch.py --parcels parcels.geojson --from 2026-05-01 --to 2026-07-31
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from analyze import MIN_VALID_PCT, SCL_KEEP, parcel_masks
from common import to_10m

STAC_SEARCH = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
TILE = "35TPN"

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

# Three clear dates, plus 2026-07-28 (two thirds cloud over demo1) to test the cloud mask.
DATES = ["2026-06-28", "2026-06-30", "2026-07-18", "2026-07-28"]

# ~12 x 12 km around Orhei; only used to look at the zone and choose the demo parcel.
AREA_BBOX = (28.745, 47.332, 28.905, 47.440)
AREA_ASSETS = ["visual", "red", "nir", "scl", "blue", "rededge1", "nir08"]
PARCEL_ASSETS = ["visual", "red", "nir", "nir08", "swir16", "scl"]

# Extra ground around a parcel, so a cloud just outside it can still be widened into it.
PARCEL_MARGIN_M = 100
# Windows are snapped to the 20 m grid, so each 20 m pixel covers exactly 2x2 pixels of 10 m.
GRID_M = 20

# SCL classes that are surely unusable: no data, saturated, cloud shadow, clouds, cirrus, snow.
# Only used here to pick between two scenes of the same day; the real mask lives in the analysis.
SCL_UNUSABLE = [0, 1, 3, 8, 9, 10, 11]

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "VSI_CACHE": "TRUE",
}


def search(bbox, start, end=None):
    """STAC items of our tile that intersect bbox (lon/lat), from day `start` to day `end`, by day."""
    body = {
        "collections": [COLLECTION],
        "bbox": [float(v) for v in bbox],
        "datetime": f"{start}T00:00:00Z/{end or start}T23:59:59Z",
        "limit": 100,
    }
    url, items = STAC_SEARCH, []
    while url:
        r = requests.post(url, json=body, timeout=60)
        r.raise_for_status()
        page = r.json()
        items += [f for f in page["features"] if f"_{TILE}_" in f["id"]]
        nxt = next((link for link in page.get("links", []) if link.get("rel") == "next"), None)
        url, body = (nxt["href"], nxt.get("body", body)) if nxt else (None, body)
    by_day = {}
    for f in sorted(items, key=lambda f: f["id"]):
        by_day.setdefault(f["properties"]["datetime"][:10], []).append(f)
    return by_day


def snapped_bounds(href, bbox, margin):
    """UTM bounds of bbox (lon/lat) plus margin, snapped outward to the 20 m grid of the tile."""
    with rasterio.open(href) as ds:
        x0, y0 = ds.transform.c, ds.transform.f
        xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", ds.crs, *bbox, densify_pts=21)
        crs = ds.crs.to_string()
    c0 = math.floor((xmin - margin - x0) / GRID_M)
    c1 = math.ceil((xmax + margin - x0) / GRID_M)
    r0 = math.floor((y0 - ymax - margin) / GRID_M)
    r1 = math.ceil((y0 - ymin + margin) / GRID_M)
    return [x0 + c0 * GRID_M, y0 - r1 * GRID_M, x0 + c1 * GRID_M, y0 - r0 * GRID_M], crs


def blocks_bytes(ds, win):
    """Compressed size of the internal COG blocks the window touches, i.e. what GDAL downloads."""
    bh, bw = ds.block_shapes[0]
    rows = range(win.row_off // bh, (win.row_off + win.height - 1) // bh + 1)
    cols = range(win.col_off // bw, (win.col_off + win.width - 1) // bw + 1)
    bands = range(1, ds.count + 1) if ds.interleaving and ds.interleaving.name == "BAND" else [1]
    return sum(ds.block_size(b, i, j) for b in bands for i in rows for j in cols)


def read_window(href, bounds, out_path):
    """Save the `bounds` window of a remote COG as a small GeoTIFF. Returns bytes fetched."""
    with rasterio.open(href) as ds:
        res = ds.transform.a
        col = (bounds[0] - ds.transform.c) / res
        row = (ds.transform.f - bounds[3]) / res
        width = (bounds[2] - bounds[0]) / res
        height = (bounds[3] - bounds[1]) / res
        # The bounds sit on the 20 m grid, so they must fall exactly on pixel edges of every band.
        assert all(abs(v - round(v)) < 1e-6 for v in (col, row, width, height)), href
        win = Window(round(col), round(row), round(width), round(height))
        data = ds.read(window=win)
        fetched = blocks_bytes(ds, win)
        profile = {
            "driver": "GTiff",
            "dtype": ds.dtypes[0],
            "count": ds.count,
            "width": win.width,
            "height": win.height,
            "crs": ds.crs,
            "transform": ds.window_transform(win),
            "nodata": ds.nodata,
            "compress": "deflate",
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data)
    return fetched


def usable_pct(scl_path):
    with rasterio.open(scl_path) as ds:
        scl = ds.read(1)
    return 100.0 * np.isin(scl, SCL_UNUSABLE, invert=True).mean()


def parcel_usable_pct(scl_path, geometry):
    """Share of the shrunken parcel whose SCL class the analysis keeps, before the mask is widened.

    Widening only removes pixels, so valid_pct in the analysis can never be higher than this.
    """
    with rasterio.open(scl_path) as ds:
        scl10 = to_10m(ds.read(1))
        _, inner = parcel_masks(geometry, ds.transform * Affine.scale(0.5), ds.crs, scl10.shape)
    return 100.0 * np.isin(scl10[inner], SCL_KEEP).mean() if inner.any() else 0.0


def fetch_region(name, bbox, assets, dates, margin, geometry=None, items_by_date=None):
    region_dir = CACHE / name
    index_path = region_dir / "scenes.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {"region": name, "bbox_lonlat": [float(v) for v in bbox], "scenes": []}

    def complete(s):
        if not s.get("bands_downloaded", True):
            return (region_dir / s["item_id"] / "scl.tif").exists()
        return all((region_dir / s["item_id"] / f"{a}.tif").exists() for a in assets)

    def usable(scl_path):
        return parcel_usable_pct(scl_path, geometry) if geometry else usable_pct(scl_path)

    done = {s["date"] for s in index["scenes"] if complete(s)}
    total = 0
    for date in dates:
        if date in done:
            print(f"{name} {date}: already on disk, nothing downloaded")
            continue
        t0 = time.time()
        items = (items_by_date or {}).get(date) or search(bbox, date).get(date, [])
        if not items:
            print(f"{name} {date}: no scene of tile {TILE}")
            continue
        if "bounds_utm" not in index:
            index["bounds_utm"], index["crs"] = snapped_bounds(items[0]["assets"]["scl"]["href"], bbox, margin)
        bounds = index["bounds_utm"]

        # Several scenes on the same day: keep the one with the most usable pixels
        # (in the shrunken parcel for a parcel, in the window for the area).
        fetched = 0
        candidates = []
        for it in items:
            scl_path = region_dir / it["id"] / "scl.tif"
            if not scl_path.exists():
                fetched += read_window(it["assets"]["scl"]["href"], bounds, scl_path)
            candidates.append({"item_id": it["id"], "usable_pct": round(usable(scl_path), 1)})
        best = max(range(len(items)), key=lambda k: candidates[k]["usable_pct"])
        item = items[best]

        bands = bool(not geometry or candidates[best]["usable_pct"] >= MIN_VALID_PCT)
        for a in assets if bands else []:
            path = region_dir / item["id"] / f"{a}.tif"
            if not path.exists():
                fetched += read_window(item["assets"][a]["href"], bounds, path)

        props = item["properties"]
        entry = {
            "date": date,
            "item_id": item["id"],
            "datetime": props["datetime"],
            "platform": props.get("platform"),
            "processing_baseline": props.get("s2:processing_baseline"),
            "boa_offset_applied": props.get("earthsearch:boa_offset_applied"),
            "scene_cloud_pct": props.get("eo:cloud_cover"),
            "usable_pct": candidates[best]["usable_pct"],
            "bands_downloaded": bands,
            "candidates": candidates,
        }
        index["scenes"] = sorted([s for s in index["scenes"] if s["date"] != date] + [entry], key=lambda s: s["date"])
        region_dir.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index, indent=2))

        on_disk = sum(p.stat().st_size for p in (region_dir / item["id"]).glob("*.tif"))
        others = ", ".join(f"{c['item_id']} {c['usable_pct']}%" for c in candidates if c["item_id"] != item["id"])
        print(
            f"{name} {date}: {item['id']}  scene clouds {props.get('eo:cloud_cover'):.1f}%  "
            f"usable in {'parcel' if geometry else 'window'} {candidates[best]['usable_pct']}%  "
            + ("" if bands else "too cloudy, bands not downloaded  ")
            + f"read ~{fetched / 1e6:.1f} MB, on disk {on_disk / 1e6:.2f} MB, {time.time() - t0:.0f} s"
            + (f"  (also seen: {others})" if others else "")
        )
        total += fetched
    return total


def flatten(coords):
    if isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from flatten(c)


def parcel_regions(path):
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    for f in gj["features"]:
        pts = np.array([p[:2] for p in flatten(f["geometry"]["coordinates"])])
        bbox = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
        yield f["properties"]["parcel_id"], bbox, f["geometry"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--area", action="store_true", help="overview around Orhei, to choose the parcel")
    what.add_argument("--parcels", help="GeoJSON with parcel polygons in lon/lat")
    ap.add_argument("--dates", nargs="+", default=DATES)
    ap.add_argument("--from", dest="start", help="every scene from this day (YYYY-MM-DD), instead of --dates")
    ap.add_argument("--to", dest="end", help="last day for --from")
    args = ap.parse_args()

    t0 = time.time()
    with rasterio.Env(**GDAL_ENV):
        if args.area:
            total = fetch_region("area", AREA_BBOX, AREA_ASSETS, args.dates, margin=0)
        else:
            total = 0
            for pid, bbox, geometry in parcel_regions(args.parcels):
                by_day = search(bbox, args.start, args.end) if args.start else None
                dates = sorted(by_day) if by_day else args.dates
                total += fetch_region(pid, bbox, PARCEL_ASSETS, dates, PARCEL_MARGIN_M, geometry, by_day)
    print(f"total read from the network: ~{total / 1e6:.0f} MB in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
