"""Step 5 study: how the overlay and the photo look on the map, before choosing.

Leaflet stretches a PNG between four lon/lat edges with north up, but our rasters are on the UTM
grid, rotated by ~1.4 degrees here. So every display image is reprojected to Web Mercator
(EPSG:3857, the projection of the web map) on a fine grid with nearest-neighbour resampling.
That fixes the alignment and keeps 10 m pixels as sharp squares when enlarged.

Writes to out/<parcel>/:
  overlay_styles.png     three overlay styles over the photo; real first scene and a TEST row
                         with a planted patch (only here, never in the results)
  overlay_sharpness.png  what the browser does to a 10 m PNG it has to enlarge, vs our reprojection
  photo_variants.png     the ESA true-colour image as is, and with one fixed brightening

    python measure_overlay.py demo1
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform, transform_bounds

from analyze import MIN_VALID_PCT, analyze_scene, weak_zones
from common import OUT, load_index, load_parcels
from measure_sector import patch_at

DISPLAY_RES_M = 1.25   # ground size of one display pixel: each 10 m pixel becomes 8 x 8
MARGIN_M = 40          # ground around the parcel shown in the photo
OUTSIDE, NORMAL, WEAK, HIDDEN = 0, 1, 2, 3


def display_grid(geometry, lat):
    """Web Mercator grid around the parcel: transform, width, height, [south, west, north, east]."""
    lons = [p[0] for p in geometry["coordinates"][0]]
    lats = [p[1] for p in geometry["coordinates"][0]]
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", "EPSG:3857", min(lons), min(lats), max(lons), max(lats))
    k = 1 / np.cos(np.radians(lat))  # Web Mercator metres per ground metre at this latitude
    res, margin = DISPLAY_RES_M * k, MARGIN_M * k
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    width, height = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))
    t = from_origin(x0, y1, res, res)
    (west, east), (north, south) = transform("EPSG:3857", "EPSG:4326", [x0, x0 + width * res], [y1, y1 - height * res])
    return t, width, height, [south, west, north, east]


def to_display(arr, src_t, src_crs, dst_t, w, h, resampling=Resampling.nearest, fill=0):
    bands = arr if arr.ndim == 3 else arr[None]
    out = np.full((bands.shape[0], h, w), fill, dtype=bands.dtype)
    for i in range(bands.shape[0]):
        reproject(bands[i], out[i], src_transform=src_t, src_crs=src_crs, dst_transform=dst_t,
                  dst_crs="EPSG:3857", resampling=resampling)
    return out if arr.ndim == 3 else out[0]


def classes(a, weak):
    c = np.full(a["ndvi"].shape, OUTSIDE, np.uint8)
    c[a["inner"]] = NORMAL
    c[a["inner"] & ~a["valid"]] = HIDDEN
    c[weak] = WEAK
    return c


def style_zones(c, dev):
    rgba = np.zeros(c.shape + (4,), np.uint8)
    rgba[c == WEAK] = (230, 30, 30, 170)
    rgba[c == HIDDEN] = (128, 128, 128, 110)
    return rgba


def style_deviation(c, dev):
    """Every valid pixel coloured by how far it is from the parcel median: red below, green above."""
    rgba = np.zeros(c.shape + (4,), np.uint8)
    d = np.nan_to_num(dev)
    below = (c == NORMAL) | (c == WEAK)
    t = np.clip(-d / 0.10, 0, 1)                 # 0 at the median, 1 at the weak threshold
    u = np.clip(d / 0.10, 0, 1)
    rgba[..., 0] = np.where(d < 0, 230, 40)
    rgba[..., 1] = np.where(d < 0, 200 - 170 * t, 170)
    rgba[..., 2] = np.where(d < 0, 30, 60)
    rgba[..., 3] = np.where(below, np.where(d < 0, 40 + 160 * t, 40 + 100 * u), 0).astype(np.uint8)
    rgba[c == HIDDEN] = (128, 128, 128, 110)
    return rgba


def style_outlined(c, dev):
    """Weak zones lightly filled with a solid edge, so small zones stay visible when zoomed out."""
    rgba = style_zones(c, dev)
    weak = c == WEAK
    rgba[weak] = (230, 30, 30, 90)
    edge = weak & ~(np.roll(weak, 1, 0) & np.roll(weak, -1, 0) & np.roll(weak, 1, 1) & np.roll(weak, -1, 1))
    for _ in range(2):  # 3 display pixels wide
        edge |= weak & (np.roll(edge, 1, 0) | np.roll(edge, -1, 0) | np.roll(edge, 1, 1) | np.roll(edge, -1, 1))
    rgba[edge] = (170, 0, 0, 255)
    return rgba


STYLES = {"A: weak zones only": style_zones, "B: deviation from median": style_deviation,
          "C: zones with outline": style_outlined}


def over(photo, rgba):
    alpha = rgba[..., 3:4] / 255
    return (photo * (1 - alpha) + rgba[..., :3] * alpha).astype(np.uint8)


def label_img(arr, lines, size=20):
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for k, line in enumerate(lines):
        d.text((8, 6 + (size + 4) * k), line, font=ImageFont.load_default(size=size), fill="white",
               stroke_width=3, stroke_fill="black")
    return img


def grid(rows, path, scale=0.5):
    rows = [[im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS) for im in r] for r in rows]
    w, h = rows[0][0].size
    out = Image.new("RGB", (len(rows[0]) * (w + 6), len(rows) * (h + 6)), "white")
    for i, r in enumerate(rows):
        for j, im in enumerate(r):
            out.paste(im, (j * (w + 6), i * (h + 6)))
    out.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    scene = next(s for s in load_index(args.parcel)["scenes"]
                 if analyze_scene(args.parcel, parcel, s)["valid_pct"] >= MIN_VALID_PCT)
    a = analyze_scene(args.parcel, parcel, scene)
    lat = np.mean([p[1] for p in parcel["geometry"]["coordinates"][0]])
    dst_t, w, h, bounds = display_grid(parcel["geometry"], lat)
    print(f"display grid: {w} x {h} px of {DISPLAY_RES_M} m, overlay_bounds [S, W, N, E] = "
          f"[{bounds[0]:.6f}, {bounds[1]:.6f}, {bounds[2]:.6f}, {bounds[3]:.6f}]")

    tci = np.moveaxis(a["rgb"], -1, 0)
    photo = np.moveaxis(to_display(tci, a["transform"], a["crs"], dst_t, w, h), 0, -1)
    bright = (np.clip((photo / 255) ** 0.8 * 1.6, 0, 1) * 255).astype(np.uint8)

    cases = []
    median, _, weak = weak_zones(a["ndvi"], a["valid"])
    cases.append((f"{scene['date']} real", a["ndvi"], weak, median))
    test = a["ndvi"].copy()
    test[patch_at(a["valid"], 25, 75, 0.10)] -= 0.20
    tmed, _, tweak = weak_zones(test, a["valid"])
    cases.append(("TEST: planted patch NE", test, tweak, tmed))

    rows = []
    for name, nd, wk, med in cases:
        c = to_display(classes(a, wk), a["transform"], a["crs"], dst_t, w, h)
        dev_src = np.where(a["valid"], nd - med, np.nan).astype(np.float32)
        dev = to_display(dev_src, a["transform"], a["crs"], dst_t, w, h, fill=np.nan)
        row = [label_img(bright, [name, "photo"])]
        for sname, fn in STYLES.items():
            row.append(label_img(over(bright, fn(c, dev)), [name, sname]))
        rows.append(row)
    grid(rows, OUT / args.parcel / "overlay_styles.png")

    # Sharpness: the browser enlarges a 10 m PNG smoothly (bilinear); ours is already enlarged by copying.
    tc = classes(a, tweak)
    native = style_zones(tc, None)
    rows_px, cols_px = np.nonzero(tweak)
    r0, c0 = int(rows_px.min()) - 3, int(cols_px.min()) - 3
    crop = native[r0:r0 + 24, c0:c0 + 24]
    blurry = np.asarray(Image.fromarray(crop, "RGBA").resize((24 * 8, 24 * 8), Image.BILINEAR))
    sharp = np.asarray(Image.fromarray(crop, "RGBA").resize((24 * 8, 24 * 8), Image.NEAREST))
    white = np.full((24 * 8, 24 * 8, 3), 255, np.uint8)
    grid([[label_img(over(white, blurry), ["browser enlarges", "a 10 m PNG"], 14),
           label_img(over(white, sharp), ["we enlarge first,", "pixel copy"], 14)]],
         OUT / args.parcel / "overlay_sharpness.png", scale=2)

    grid([[label_img(photo, ["ESA true colour, as is"]), label_img(bright, ["same, fixed brightening"])]],
         OUT / args.parcel / "photo_variants.png")
    print(f"written {OUT / args.parcel}: overlay_styles.png, overlay_sharpness.png, photo_variants.png")


if __name__ == "__main__":
    main()
