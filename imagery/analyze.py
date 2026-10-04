"""Parcel analysis from the cache only; no network.

For every parcel of the parcels file (common.PARCELS) and every scene cached for it (fetch.py --parcels):
  1. shrink the polygon: keep pixels whose centre is more than SHRINK_M inside the outline
  2. cloud mask from SCL: keep only the classes in SCL_KEEP, widen the rest by WIDEN_M
  3. valid_pct = share of the shrunken parcel left after the mask; below MIN_VALID_PCT the
     scene is skipped for that parcel and listed under "skipped" with the reason
  4. ndvi_median of the valid pixels; a pixel is weak if its NDVI is more than DROP_NDVI below it
  5. weak zones (8-connected) smaller than MIN_ZONE_PX are dropped, and in orchards and vineyards
     (ROW_CROPS) first the strips narrower than ROW_OPENING_PX pixels (the grass between the rows);
     affected_pct is the share of valid pixels left in weak zones after that cleanup
  6. affected_sector: compass direction from the parcel centre to the centre of the largest zone
     (C when it is in the inner third of the parcel radius), or "scattered" when the largest zone
     holds less of the weak area than SCATTERED_BELOW_PCT; zone_count; zone_center as [lon, lat]
  7. overlay and photo for the map, reprojected to Web Mercator (the web map's projection) on a
     DISPLAY_RES_M grid by copying pixels, so they line up with the map and stay sharp
  8. warnings; low_vegetation (below the crop's NDVI) and whole_field_drop only in the crop's growing
     season (crop calendar of sensors-alerts): before and after it, low or falling NDVI is normal

Writes out/imagery.json ({"rules_version", "results": [...], "skipped": [...]}), out/overlays/<parcel>_<date>.png
and <parcel>_<date>_rgb.png; with --check-images also out/<parcel>/mask.png and weak.png, every date side by side.
The decisions behind every constant are in LOGIC.md.

    python analyze.py                  # what the daily job runs
    python analyze.py --check-images   # plus the check images, for a person to look at
"""
import argparse
import hashlib
import json
from datetime import date as Date

import numpy as np
import rasterio.transform
from PIL import Image, ImageDraw, ImageFont
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject, transform, transform_bounds, transform_geom
from scipy.ndimage import binary_dilation, binary_opening, distance_transform_edt, label

from common import HERE, OUT, crop_calendar, load_index, load_parcels, ndvi, phase_on, polygon_mask, polygon_pixels, \
    read_asset, reflectance, to_10m

SCL_KEEP = [4, 5, 6]     # vegetation, bare soil, water; any other class is suspicious in a field
WIDEN_M = 20             # the mask grows by one 20 m SCL pixel around everything thrown away
SHRINK_M = 20            # border pixels mix the field with the road or the neighbour
MIN_VALID_PCT = 50       # below this the parcel median is not representative: skip the scene
LOW_CONFIDENCE_PX = 200  # fewer pixels than this after shrinking: flag the result
DROP_NDVI = 0.10         # weak = more than this below the parcel median of the same scene
MIN_ZONE_PX = 10         # weak zones smaller than this (0.1 ha) are noise, a pylon, a bare spot
CENTRE_FRACTION = 1 / 3  # a zone this close to the centre (share of the parcel radius) is "C"
SCATTERED_BELOW_PCT = 50 # largest zone holds less of the weak area than this: no single direction
DIRECTIONS = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]  # counter-clockwise from east, 45 degrees each
SCL_RES_M = 20

DISPLAY_RES_M = 1.25               # ground size of a display pixel: each 10 m pixel becomes 8 x 8
PHOTO_MARGIN_M = 40                # ground shown around the parcel; the overlay uses the same corners
WEAK_RGBA = (230, 30, 30, 170)     # red, 67% opaque
HIDDEN_RGBA = (128, 128, 128, 110) # grey, 43% opaque: part of the parcel the clouds hid
OUTLINE_RGBA = (255, 255, 255, 230)
OUTLINE_PX = 2                     # white ring just outside every weak zone, 2.5 m wide
PHOTO_GAIN, PHOTO_GAMMA = 1.6, 0.8 # one fixed brightening of ESA's true-colour image, same for every date
OUTSIDE, NORMAL, WEAK, HIDDEN = 0, 1, 2, 3

LOW_VEGETATION_NDVI = 0.6 # below this median the canopy is incomplete; the weak rule was validated at ~0.75
# A 10 m pixel of a vineyard or an orchard mixes the rows with the grass between them, so their NDVI stays lower.
CROP_LOW_VEGETATION_NDVI = {"vineyard": 0.4, "orchard": 0.5}
# Rows and alleys of grass: weak strips under 3 pixels (30 m) wide are dropped there, compact patches stay.
ROW_CROPS = {"orchard", "vineyard"}
ROW_OPENING_PX = 3
WHOLE_PARCEL_DROP = 0.10  # parcel median fell by more than this since the previous scene
# low_vegetation and whole_field_drop are warnings only while the crop should be green; before it has grown
# (or in winter) and once it ripens or is harvested, a low or falling NDVI is normal (crop calendar, common.py).
WARN_SEASONS = {"growing"}
MAX_GAP_DAYS = 30         # an older previous scene says little about what changed
CLOUD_NEAR_M = 100        # a declined zone this close to masked pixels may be a cloud the mask missed
PIXEL_M = 10

OUTPUT = OUT / "imagery.json"
# The files whose code decides the results; their fingerprint is the rules_version of every result.
RULES_FILES = ["analyze.py", "common.py"]
OVERLAYS = OUT / "overlays"


def disk(radius_px):
    y, x = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    return x * x + y * y <= radius_px * radius_px


def distance_to_outline(xs, ys, geom):
    """Distance from points to the nearest edge of a (multi)polygon, in the units of the coordinates."""
    polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best = np.full(xs.shape, np.inf)
    for polygon in polygons:
        for ring in polygon:
            for (ax, ay), (bx, by) in zip(ring[:-1], ring[1:]):
                dx, dy = bx - ax, by - ay
                t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / max(dx * dx + dy * dy, 1e-12), 0, 1)
                best = np.minimum(best, np.hypot(xs - (ax + t * dx), ys - (ay + t * dy)))
    return best


def parcel_masks(geometry, transform, crs, shape):
    """Pixels inside the polygon, and those whose centre is more than SHRINK_M from its edge."""
    inside = polygon_mask(geometry, transform, crs, shape)
    rows, cols = np.nonzero(inside)
    xs, ys = (np.asarray(v) for v in rasterio.transform.xy(transform, rows, cols))
    far = distance_to_outline(xs, ys, transform_geom("EPSG:4326", crs, geometry)) > SHRINK_M
    inner = np.zeros(shape, bool)
    inner[rows[far], cols[far]] = True
    return inside, inner


def invalid_pixels(scl20, red=None, nir=None):
    """Pixels not to be used, on the 10 m grid: unwanted SCL classes widened by WIDEN_M, and no data."""
    bad = ~np.isin(scl20, SCL_KEEP)
    radius = WIDEN_M // SCL_RES_M
    if radius:
        bad = binary_dilation(bad, structure=disk(radius))
    bad = to_10m(bad)
    if red is None:
        return bad
    assert bad.shape == red.shape, (bad.shape, red.shape)
    return bad | np.isnan(red) | np.isnan(nir)


def scl_only_valid_pct(parcel_id, parcel, scene):
    """valid_pct of a scene whose bands were not downloaded, from SCL alone (no data is an SCL class too)."""
    scl, t20, crs = read_asset(parcel_id, scene, "scl")
    invalid = invalid_pixels(scl[0])
    _, inner = parcel_masks(parcel["geometry"], t20 * Affine.scale(0.5), crs, invalid.shape)
    return round(100 * (inner & ~invalid).sum() / inner.sum(), 1) if inner.any() else 0.0


def sheet(images, legend, path, cols=6):
    """Images in rows of `cols`, with a one-line legend under them."""
    w, h = images[0].size
    n_rows = (len(images) + cols - 1) // cols
    out = Image.new("RGB", (max(min(len(images), cols) * (w + 6), 900), n_rows * (h + 6) + 26), "white")
    for i, img in enumerate(images):
        out.paste(img, ((i % cols) * (w + 6), (i // cols) * (h + 6)))
    ImageDraw.Draw(out).text((6, n_rows * (h + 6) + 4), legend, font=ImageFont.load_default(size=15), fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    return path


def analyze_scene(parcel_id, parcel, scene):
    red = reflectance(read_asset(parcel_id, scene, "red")[0][0], scene)
    nir = reflectance(read_asset(parcel_id, scene, "nir")[0][0], scene)
    scl20 = read_asset(parcel_id, scene, "scl")[0][0]
    visual, transform, crs = read_asset(parcel_id, scene, "visual")
    inside, inner = parcel_masks(parcel["geometry"], transform, crs, red.shape)
    invalid = invalid_pixels(scl20, red, nir)
    valid = inner & ~invalid
    n_inner = int(inner.sum())
    # NDMI = (B8A - B11) / (B8A + B11): water in the leaves, at 20 m, copied onto the 10 m grid.
    nir08 = reflectance(read_asset(parcel_id, scene, "nir08")[0][0], scene)
    swir16 = reflectance(read_asset(parcel_id, scene, "swir16")[0][0], scene)
    ndmi = to_10m(ndvi(swir16, nir08))
    return {
        "inside": inside, "inner": inner, "invalid": invalid, "valid": valid, "ndvi": ndvi(red, nir), "ndmi": ndmi,
        "rgb": np.moveaxis(visual, 0, -1), "ring": polygon_pixels(parcel["geometry"], transform, crs),
        "transform": transform, "crs": crs,
        "n_inside": int(inside.sum()), "n_inner": n_inner, "n_valid": int(valid.sum()),
        "valid_pct": round(100 * valid.sum() / n_inner, 1) if n_inner else 0.0,
    }


def remove_small_zones(weak, min_px):
    """Drop groups of touching weak pixels (diagonal neighbours count) smaller than min_px."""
    labels, n = label(weak, structure=np.ones((3, 3), bool))
    if n == 0:
        return weak
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[labels]


def weak_zones(ndvi_map, valid, rows=False):
    """Parcel median, weak pixels before cleanup and weak pixels left after removing small zones. With rows
    (orchard, vineyard), weak strips narrower than ROW_OPENING_PX pixels go first: the grass between the rows."""
    median = float(np.median(ndvi_map[valid]))
    raw = valid & (ndvi_map < median - DROP_NDVI)
    kept = binary_opening(raw, structure=np.ones((ROW_OPENING_PX, ROW_OPENING_PX), bool)) if rows else raw
    return median, raw, remove_small_zones(kept, MIN_ZONE_PX)


def direction_of(row, col, centre, radius_px):
    """Compass direction from the parcel centre to (row, col), or C near the centre; rows grow southwards."""
    dy, dx = centre[0] - row, col - centre[1]
    if np.hypot(dx, dy) < CENTRE_FRACTION * radius_px:
        return "C"
    angle = np.degrees(np.arctan2(dy, dx)) % 360
    return DIRECTIONS[int(((angle + 22.5) % 360) // 45)]


def zone_location(weak, inner, grid_transform, crs):
    """affected_sector, zone_count, zone_center ([lon, lat] of the largest zone's centre) and the
    pixels of that main zone (None when there is no zone or the zones are scattered)."""
    labels, n = label(weak, structure=np.ones((3, 3), bool))
    if n == 0:
        return None, 0, None, None
    sizes = np.bincount(labels.ravel())[1:]
    if 100 * sizes.max() / sizes.sum() < SCATTERED_BELOW_PCT:
        return "scattered", n, None, None
    main_zone = labels == np.argmax(sizes) + 1
    rows, cols = np.nonzero(main_zone)
    zr, zc = rows.mean(), cols.mean()
    pr, pc = np.nonzero(inner)
    sector = direction_of(zr, zc, (pr.mean(), pc.mean()), np.sqrt(len(pr) / np.pi))
    # The map marker must sit on the zone; a curved zone's centroid can fall outside it, so the
    # marker is the zone pixel nearest to the centroid.
    k = np.argmin((rows - zr) ** 2 + (cols - zc) ** 2)
    x, y = grid_transform * (cols[k] + 0.5, rows[k] + 0.5)  # centre of that pixel
    lon, lat = transform(crs, "EPSG:4326", [x], [y])
    return sector, n, [round(lon[0], 6), round(lat[0], 6)], main_zone


def display_grid(geometry):
    """Web Mercator grid around the parcel plus PHOTO_MARGIN_M: transform, width, height and the
    exact [south, west, north, east] of its edges, which Leaflet needs to place the PNG."""
    lons = [p[0] for p in geometry["coordinates"][0]]
    lats = [p[1] for p in geometry["coordinates"][0]]
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", "EPSG:3857", min(lons), min(lats), max(lons), max(lats))
    k = 1 / np.cos(np.radians(np.mean(lats)))  # Web Mercator metres per ground metre at this latitude
    res, margin = DISPLAY_RES_M * k, PHOTO_MARGIN_M * k
    x0, y1 = x0 - margin, y1 + margin
    width = int(np.ceil((x1 + margin - x0) / res))
    height = int(np.ceil((y1 - (y0 - margin)) / res))
    (west, east), (north, south) = transform("EPSG:3857", "EPSG:4326", [x0, x0 + width * res], [y1, y1 - height * res])
    bounds = [round(south, 6), round(west, 6), round(north, 6), round(east, 6)]
    return from_origin(x0, y1, res, res), width, height, bounds


def to_display(arr, src_transform, src_crs, grid):
    """Reproject a (bands, rows, cols) or (rows, cols) array onto the display grid by copying pixels."""
    dst_transform, width, height, _ = grid
    bands = arr if arr.ndim == 3 else arr[None]
    out = np.zeros((bands.shape[0], height, width), dtype=bands.dtype)
    for i in range(bands.shape[0]):
        reproject(bands[i], out[i], src_transform=src_transform, src_crs=src_crs, dst_transform=dst_transform,
                  dst_crs="EPSG:3857", resampling=Resampling.nearest)
    return out if arr.ndim == 3 else out[0]


def write_overlay(a, grid, path):
    """Transparent PNG: weak zones red with a thin white ring around them, cloud-hidden parts grey."""
    c = np.full(a["ndvi"].shape, OUTSIDE, np.uint8)
    c[a["inner"]] = NORMAL
    c[a["inner"] & ~a["valid"]] = HIDDEN
    c[a["weak"]] = WEAK
    c = to_display(c, a["transform"], a["crs"], grid)
    rgba = np.zeros(c.shape + (4,), np.uint8)
    rgba[c == HIDDEN] = HIDDEN_RGBA
    weak = c == WEAK
    ring = binary_dilation(weak, structure=np.ones((3, 3), bool), iterations=OUTLINE_PX) & ~weak
    rgba[ring] = OUTLINE_RGBA
    rgba[weak] = WEAK_RGBA
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)


def write_photo(a, grid, path):
    rgb = np.moveaxis(to_display(np.moveaxis(a["rgb"], -1, 0), a["transform"], a["crs"], grid), 0, -1)
    rgb = (np.clip((rgb / 255) ** PHOTO_GAMMA * PHOTO_GAIN, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(path, optimize=True)


def compare_with_previous(prev, cur):
    """Change since the previous accepted scene, on pixels valid in both.

    A pixel declined if its NDVI fell more than DROP_NDVI MORE than the parcel median did, so a
    change of the whole field (ripening, growth, the offset between satellites) cancels out.
    Returns the median change, the declined pixels (small zones removed) and the pixels compared.
    """
    both = prev["valid"] & cur["valid"]
    relative = (cur["ndvi"] - cur["median"]) - (prev["ndvi"] - prev["median"])
    declined = remove_small_zones(both & (relative < -DROP_NDVI), MIN_ZONE_PX)
    return cur["median"] - prev["median"], declined, both


def zones_near_mask(zones, invalid):
    """How many zones have a pixel within CLOUD_NEAR_M of a pixel thrown away by the cloud mask."""
    if not invalid.any() or not zones.any():
        return 0
    near = PIXEL_M * distance_transform_edt(~invalid) <= CLOUD_NEAR_M
    labels, _ = label(zones, structure=np.ones((3, 3), bool))
    return len(np.setdiff1d(np.unique(labels[near & zones]), [0]))


def warning(code, text):
    """A warning has a fixed code for programs (the priority score) and a text for people."""
    return {"code": code, "text": text}


def change_since(prev, cur, date, season="growing", phase=None):
    """prev_scene_date, median_change and declined_pct for the result, the warnings they raise
    (stale_previous; whole_field_drop while the crop should be green) and the declined pixels (None for the
    first scene)."""
    if prev is None:
        return {"prev_scene_date": None, "median_change": None, "declined_pct": None}, [], None
    median_change, declined, both = compare_with_previous(prev, cur)
    warnings = []
    gap = (Date.fromisoformat(date) - Date.fromisoformat(prev["date"])).days
    if gap > MAX_GAP_DAYS:
        warnings.append(warning("stale_previous",
                                f"previous scene is {gap} days older ({prev['date']}): the comparison says little"))
    if median_change < -WHOLE_PARCEL_DROP and season in WARN_SEASONS:
        warnings.append(warning("whole_field_drop",
                                f"the whole parcel dropped by {-median_change:.2f} NDVI since {prev['date']} while the "
                                f"crop should still be green ({phase or 'no crop calendar'}): hail, drought, early "
                                f"drying or mowing; the image alone cannot tell"))
    change = {"prev_scene_date": prev["date"], "median_change": round(median_change, 3),
              "declined_pct": round(100 * declined.sum() / both.sum(), 1)}
    return change, warnings, declined


def possible_cloud(weak, declined, invalid):
    """possible_cloud warning when weak or declined zones touch the cloud mask's surroundings, else None."""
    counts = [(zones_near_mask(weak, invalid), "weak"),
              (zones_near_mask(declined, invalid) if declined is not None else 0, "declined")]
    found = [f"{n} {kind} zone(s)" for n, kind in counts if n]
    if not found:
        return None
    return warning("possible_cloud", f"{' and '.join(found)} within {CLOUD_NEAR_M} m of cloud-masked pixels: "
                                     f"possibly a cloud the mask missed")


def render_weak(parcel_id, panels):
    """One panel per accepted date: NDVI in grey, weak zones kept in red, small zones dropped in yellow."""
    scale = 4
    font = ImageFont.load_default(size=18)
    images = []
    for title, a in panels:
        v = a["ndvi"][a["valid"]]
        lo, hi = np.percentile(v, [2, 98])
        g = np.clip((np.nan_to_num(a["ndvi"]) - lo) / (hi - lo), 0, 1) * 200 + 40
        rgb = np.stack([g, g, g], -1)
        rgb[~a["valid"]] *= 0.3
        rgb[a["weak_raw"] & ~a["weak"]] = (255, 220, 0)
        rgb[a["weak"]] = (230, 30, 30)
        img = Image.fromarray(rgb.astype(np.uint8)).resize((rgb.shape[1] * scale, rgb.shape[0] * scale), Image.NEAREST)
        draw = ImageDraw.Draw(img)
        draw.line([(x * scale, y * scale) for x, y in a["ring"]], fill=(255, 0, 255), width=2)
        for k, line in enumerate(title):
            draw.text((6, 4 + 22 * k), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
        images.append(img)
    legend = (f"red: weak (more than {DROP_NDVI} below the median), in zones of {MIN_ZONE_PX}+ px   "
              f"yellow: weak but dropped (zones under {MIN_ZONE_PX} px; in orchards and vineyards also strips "
              f"under {ROW_OPENING_PX} px wide)   grey: NDVI, light = denser")
    return sheet(images, legend, OUT / parcel_id / "weak.png")


def render_masks(parcel_id, panels):
    """One panel per date: outside the parcel darkened, the shrink ring in orange, the cloud mask in white."""
    scale = 4
    font = ImageFont.load_default(size=18)
    images = []
    for title, a in panels:
        rgb = a["rgb"].astype(float)
        rgb[~a["inside"]] *= 0.45
        ring_px = a["inside"] & ~a["inner"]
        rgb[ring_px] = 0.4 * rgb[ring_px] + 0.6 * np.array([255, 140, 0])
        rgb[a["invalid"]] = 0.3 * rgb[a["invalid"]] + 0.7 * 255
        img = Image.fromarray(rgb.astype(np.uint8)).resize((rgb.shape[1] * scale, rgb.shape[0] * scale), Image.NEAREST)
        draw = ImageDraw.Draw(img)
        draw.line([(x * scale, y * scale) for x, y in a["ring"]], fill=(255, 0, 255), width=2)
        for k, line in enumerate(title):
            draw.text((6, 4 + 22 * k), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
        images.append(img)
    legend = "white: thrown away by the cloud mask   orange: border removed by the 20 m shrink   magenta: outline"
    return sheet(images, legend, OUT / parcel_id / "mask.png")


def rules_version(calendar):
    """Short fingerprint of the analysis code and the crop calendar: it changes whenever a rule changes."""
    digest = hashlib.sha1()
    for name in RULES_FILES:
        digest.update((HERE / name).read_bytes())
    digest.update(json.dumps(calendar, sort_keys=True).encode())
    return digest.hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check-images", action="store_true", help="also write out/<parcel>/mask.png and weak.png")
    args = ap.parse_args()
    results, skipped = [], []
    calendar = crop_calendar()
    OVERLAYS.mkdir(parents=True, exist_ok=True)
    for parcel_id, parcel in load_parcels().items():
        crop = parcel["properties"].get("crop")
        panels, weak_panels = [], []
        grid = display_grid(parcel["geometry"])
        prev = None  # previous accepted scene of this parcel
        print(f"{parcel_id}:")
        print(f"  {'date':10s} {'scene':26s} {'in polygon':>10s} {'after shrink':>12s} {'valid':>6s} {'valid_pct':>9s}  "
              f"{'median':>6s} {'weak raw':>8s} {'affected':>8s} {'zones':>5s} {'sector':>9s}  zone_center      status")
        for scene in load_index(parcel_id)["scenes"]:
            date = scene["date"]
            if not scene.get("bands_downloaded", True):
                valid_pct = scl_only_valid_pct(parcel_id, parcel, scene)
                reason = (f"only {valid_pct}% of the parcel is cloud-free (minimum {MIN_VALID_PCT}%); "
                          f"bands not downloaded")
                skipped.append({"parcel_id": parcel_id, "scene_date": date, "scene_id": scene["item_id"],
                                "valid_pct": valid_pct, "reason": reason})
                print(f"  {date:10s} {scene['item_id']:26s} {'':10s} {'':12s} {'':6s} {valid_pct:8.1f}%  "
                      f"{'':6s} {'':8s} {'':8s} {'':5s} {'':9s}  {'':16s}  SKIPPED: {reason}")
                continue
            a = analyze_scene(parcel_id, parcel, scene)
            phase, season = phase_on(calendar, crop, date)
            warnings = []
            if a["n_inner"] < LOW_CONFIDENCE_PX:
                warnings.append(warning("low_pixel_count", f"low confidence: only {a['n_inner']} pixels after the "
                                                           f"{SHRINK_M} m shrink (fewer than {LOW_CONFIDENCE_PX})"))
            if a["n_inner"] == 0:
                reason = f"no pixel left after the {SHRINK_M} m shrink"
            elif a["valid_pct"] < MIN_VALID_PCT:
                reason = f"only {a['valid_pct']}% of the parcel is cloud-free (minimum {MIN_VALID_PCT}%)"
            else:
                reason = None

            numbers = f"{'':6s} {'':8s} {'':8s} {'':5s} {'':9s}  {'':16s}"
            if reason:
                skipped.append({"parcel_id": parcel_id, "scene_date": date, "scene_id": scene["item_id"],
                                "valid_pct": a["valid_pct"], "reason": reason})
                status = "SKIPPED: " + reason
            else:
                median, a["weak_raw"], a["weak"] = weak_zones(a["ndvi"], a["valid"], rows=crop in ROW_CROPS)
                a["median"] = median
                raw_pct = 100 * a["weak_raw"].sum() / a["n_valid"]
                affected_pct = round(100 * a["weak"].sum() / a["n_valid"], 1)
                sector, n_zones, center, main_zone = zone_location(a["weak"], a["inner"], a["transform"], a["crs"])
                low_ndvi = CROP_LOW_VEGETATION_NDVI.get(crop, LOW_VEGETATION_NDVI)
                if median < low_ndvi and season in WARN_SEASONS:
                    warnings.append(warning("low_vegetation",
                                            f"parcel NDVI median {median:.2f} is below {low_ndvi} for {crop} while it "
                                            f"should be green ({phase or 'no crop calendar'}): poor growth, early drying "
                                            f"or bare patches; the weak-pixel rule was validated at NDVI ~0.75"))

                ndmi_median = round(float(np.nanmedian(a["ndmi"][a["valid"]])), 3)
                change, change_warnings, declined = change_since(prev, a, date, season, phase)
                change["ndmi_change"] = None if prev is None else round(ndmi_median - prev["ndmi_median"], 3)
                # The main zone is confirmed when it overlaps weak pixels of the previous accepted scene.
                change["zone_confirmed"] = (None if prev is None or main_zone is None
                                            else bool((main_zone & prev["weak"]).any()))
                warnings += change_warnings
                cloud = possible_cloud(a["weak"], declined, a["invalid"])
                if cloud:
                    warnings.append(cloud)
                prev = {"date": date, "ndvi": a["ndvi"], "valid": a["valid"], "median": median,
                        "ndmi_median": ndmi_median, "weak": a["weak"]}
                overlay_name, photo_name = f"{parcel_id}_{date}.png", f"{parcel_id}_{date}_rgb.png"
                write_overlay(a, grid, OVERLAYS / overlay_name)
                write_photo(a, grid, OVERLAYS / photo_name)
                results.append({"parcel_id": parcel_id, "scene_date": date, "scene_id": scene["item_id"],
                                "ndvi_median": round(median, 3),
                                "ndmi_median": ndmi_median,
                                "affected_pct": affected_pct, "affected_sector": sector, "zone_count": n_zones,
                                "zone_center": center, "valid_pct": a["valid_pct"], **change,
                                "overlay_path": f"/overlays/{overlay_name}", "photo_path": f"/overlays/{photo_name}",
                                "overlay_bounds": grid[3], "warnings": warnings})
                status = f"accepted ({phase or '-'})" + ("; " + ", ".join(w["code"] for w in warnings) if warnings else "")
                numbers = (f"{median:6.3f} {raw_pct:7.1f}% {affected_pct:7.1f}% {n_zones:5d} {str(sector):>9s}  "
                           f"{str(center):16s}")
                weak_panels.append(([date, f"median {median:.3f}", f"affected {affected_pct}%, sector {sector}",
                                     f"{n_zones} zones"], a))
            print(f"  {date:10s} {scene['item_id']:26s} {a['n_inside']:10d} {a['n_inner']:12d} {a['n_valid']:6d} "
                  f"{a['valid_pct']:8.1f}%  {numbers}  {status}")
            panels.append(([f"{date}", f"valid {a['valid_pct']}%", "accepted" if not reason else "SKIPPED"], a))
        if args.check_images:
            print(f"  mask image: {render_masks(parcel_id, panels)}")
            if weak_panels:
                print(f"  weak zones image: {render_weak(parcel_id, weak_panels)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"rules_version": rules_version(calendar), "results": results, "skipped": skipped},
                                 indent=2, ensure_ascii=False), encoding="utf-8")  # Romanian names: not the Windows code page
    print(f"written {OUTPUT}: {len(results)} results, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
