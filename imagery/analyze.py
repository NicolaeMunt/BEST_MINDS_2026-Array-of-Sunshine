"""Parcel analysis from the cache only; no network.

For every parcel in parcels.geojson and every scene cached for it (fetch.py --parcels):
  1. shrink the polygon: keep pixels whose centre is more than SHRINK_M inside the outline
  2. cloud mask from SCL: keep only the classes in SCL_KEEP, widen the rest by WIDEN_M
  3. valid_pct = share of the shrunken parcel left after the mask; below MIN_VALID_PCT the
     scene is skipped for that parcel and listed under "skipped" with the reason
  4. ndvi_median of the valid pixels; a pixel is weak if its NDVI is more than DROP_NDVI below it
  5. weak zones (8-connected) smaller than MIN_ZONE_PX are dropped; affected_pct is the share of
     valid pixels left in weak zones after that cleanup
  6. affected_sector: compass direction from the parcel centre to the centre of the largest zone
     (C when it is in the inner third of the parcel radius), or "scattered" when the largest zone
     holds less of the weak area than SCATTERED_BELOW_PCT; zone_count; zone_center as [lon, lat]
  7. overlay and photo for the map, reprojected to Web Mercator (the web map's projection) on a
     DISPLAY_RES_M grid by copying pixels, so they line up with the map and stay sharp

Writes out/imagery.json ({"results": [...], "skipped": [...]}), out/overlays/<parcel>_<date>.png
and <parcel>_<date>_rgb.png, and check images in out/<parcel>/ (mask.png, weak.png).
The decisions behind every constant are in LOGIC.md.

    python analyze.py
"""
import json

import numpy as np
import rasterio.transform
from PIL import Image, ImageDraw, ImageFont
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform, transform_bounds, transform_geom
from scipy.ndimage import binary_dilation, label

from common import OUT, load_index, load_parcels, ndvi, polygon_mask, polygon_pixels, read_asset, reflectance, \
    to_10m

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

OUTPUT = OUT / "imagery.json"
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


def invalid_pixels(scl20, red, nir):
    """Pixels not to be used, on the 10 m grid: unwanted SCL classes widened by WIDEN_M, and no data."""
    bad = ~np.isin(scl20, SCL_KEEP)
    radius = WIDEN_M // SCL_RES_M
    if radius:
        bad = binary_dilation(bad, structure=disk(radius))
    bad = to_10m(bad)
    assert bad.shape == red.shape, (bad.shape, red.shape)
    return bad | np.isnan(red) | np.isnan(nir)


def analyze_scene(parcel_id, parcel, scene):
    red = reflectance(read_asset(parcel_id, scene, "red")[0][0], scene)
    nir = reflectance(read_asset(parcel_id, scene, "nir")[0][0], scene)
    scl20 = read_asset(parcel_id, scene, "scl")[0][0]
    visual, transform, crs = read_asset(parcel_id, scene, "visual")
    inside, inner = parcel_masks(parcel["geometry"], transform, crs, red.shape)
    invalid = invalid_pixels(scl20, red, nir)
    valid = inner & ~invalid
    n_inner = int(inner.sum())
    return {
        "inside": inside, "inner": inner, "invalid": invalid, "valid": valid, "ndvi": ndvi(red, nir),
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


def weak_zones(ndvi_map, valid):
    """Parcel median, weak pixels before cleanup and weak pixels left after removing small zones."""
    median = float(np.median(ndvi_map[valid]))
    raw = valid & (ndvi_map < median - DROP_NDVI)
    return median, raw, remove_small_zones(raw, MIN_ZONE_PX)


def direction_of(row, col, centre, radius_px):
    """Compass direction from the parcel centre to (row, col), or C near the centre; rows grow southwards."""
    dy, dx = centre[0] - row, col - centre[1]
    if np.hypot(dx, dy) < CENTRE_FRACTION * radius_px:
        return "C"
    angle = np.degrees(np.arctan2(dy, dx)) % 360
    return DIRECTIONS[int(((angle + 22.5) % 360) // 45)]


def zone_location(weak, inner, grid_transform, crs):
    """affected_sector, zone_count and zone_center ([lon, lat] of the largest zone's centre)."""
    labels, n = label(weak, structure=np.ones((3, 3), bool))
    if n == 0:
        return None, 0, None
    sizes = np.bincount(labels.ravel())[1:]
    if 100 * sizes.max() / sizes.sum() < SCATTERED_BELOW_PCT:
        return "scattered", n, None
    rows, cols = np.nonzero(labels == np.argmax(sizes) + 1)
    zr, zc = rows.mean(), cols.mean()
    pr, pc = np.nonzero(inner)
    sector = direction_of(zr, zc, (pr.mean(), pc.mean()), np.sqrt(len(pr) / np.pi))
    x, y = grid_transform * (zc + 0.5, zr + 0.5)  # centre of the pixel at (zr, zc)
    lon, lat = transform(crs, "EPSG:4326", [x], [y])
    return sector, n, [round(lon[0], 6), round(lat[0], 6)]


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
    w, h = images[0].size
    legend = (f"red: weak (more than {DROP_NDVI} below the median), in zones of {MIN_ZONE_PX}+ px   "
              f"yellow: weak but in zones under {MIN_ZONE_PX} px, dropped   grey: NDVI, light = denser")
    out = Image.new("RGB", (max(len(images) * (w + 6), 900), h + 30), "white")
    for i, img in enumerate(images):
        out.paste(img, (i * (w + 6), 0))
    ImageDraw.Draw(out).text((6, h + 6), legend, font=ImageFont.load_default(size=15), fill="black")
    path = OUT / parcel_id / "weak.png"
    out.save(path)
    return path


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
    w, h = images[0].size
    legend = "white: thrown away by the cloud mask   orange: border removed by the 20 m shrink   magenta: outline"
    out = Image.new("RGB", (len(images) * (w + 6), h + 30), "white")
    for i, img in enumerate(images):
        out.paste(img, (i * (w + 6), 0))
    ImageDraw.Draw(out).text((6, h + 6), legend, font=ImageFont.load_default(size=16), fill="black")
    path = OUT / parcel_id / "mask.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    return path


def main():
    results, skipped = [], []
    OVERLAYS.mkdir(parents=True, exist_ok=True)
    for parcel_id, parcel in load_parcels().items():
        panels, weak_panels = [], []
        grid = display_grid(parcel["geometry"])
        print(f"{parcel_id}:")
        print(f"  {'date':10s} {'scene':26s} {'in polygon':>10s} {'after shrink':>12s} {'valid':>6s} {'valid_pct':>9s}  "
              f"{'median':>6s} {'weak raw':>8s} {'affected':>8s} {'zones':>5s} {'sector':>9s}  zone_center      status")
        for scene in load_index(parcel_id)["scenes"]:
            a = analyze_scene(parcel_id, parcel, scene)
            date = scene["date"]
            warnings = []
            if a["n_inner"] < LOW_CONFIDENCE_PX:
                warnings.append(f"low confidence: only {a['n_inner']} pixels after the {SHRINK_M} m shrink "
                                f"(fewer than {LOW_CONFIDENCE_PX})")
            if a["n_inner"] == 0:
                reason = f"no pixel left after the {SHRINK_M} m shrink"
            elif a["valid_pct"] < MIN_VALID_PCT:
                reason = f"only {a['valid_pct']}% of the parcel is cloud-free (minimum {MIN_VALID_PCT}%)"
            else:
                reason = None

            numbers = f"{'':6s} {'':8s} {'':8s} {'':5s} {'':9s}  {'':16s}"
            if reason:
                skipped.append({"parcel_id": parcel_id, "scene_date": date, "valid_pct": a["valid_pct"],
                                "reason": reason})
                status = "SKIPPED: " + reason
            else:
                median, a["weak_raw"], a["weak"] = weak_zones(a["ndvi"], a["valid"])
                raw_pct = 100 * a["weak_raw"].sum() / a["n_valid"]
                affected_pct = round(100 * a["weak"].sum() / a["n_valid"], 1)
                sector, n_zones, center = zone_location(a["weak"], a["inner"], a["transform"], a["crs"])
                overlay_name, photo_name = f"{parcel_id}_{date}.png", f"{parcel_id}_{date}_rgb.png"
                write_overlay(a, grid, OVERLAYS / overlay_name)
                write_photo(a, grid, OVERLAYS / photo_name)
                results.append({"parcel_id": parcel_id, "scene_date": date, "ndvi_median": round(median, 3),
                                "affected_pct": affected_pct, "affected_sector": sector, "zone_count": n_zones,
                                "zone_center": center, "valid_pct": a["valid_pct"],
                                "overlay_path": f"/overlays/{overlay_name}", "photo_path": f"/overlays/{photo_name}",
                                "overlay_bounds": grid[3], "warnings": warnings})
                status = "accepted" + ("; " + "; ".join(warnings) if warnings else "")
                numbers = (f"{median:6.3f} {raw_pct:7.1f}% {affected_pct:7.1f}% {n_zones:5d} {str(sector):>9s}  "
                           f"{str(center):16s}")
                weak_panels.append(([date, f"median {median:.3f}", f"affected {affected_pct}%, sector {sector}",
                                     f"{n_zones} zones"], a))
            print(f"  {date:10s} {scene['item_id']:26s} {a['n_inside']:10d} {a['n_inner']:12d} {a['n_valid']:6d} "
                  f"{a['valid_pct']:8.1f}%  {numbers}  {status}")
            panels.append(([f"{date}", f"valid {a['valid_pct']}%", "accepted" if not reason else "SKIPPED"], a))
        print(f"  mask image: {render_masks(parcel_id, panels)}")
        if weak_panels:
            print(f"  weak zones image: {render_weak(parcel_id, weak_panels)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"results": results, "skipped": skipped}, indent=2, ensure_ascii=False))
    print(f"written {OUTPUT}: {len(results)} results, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
