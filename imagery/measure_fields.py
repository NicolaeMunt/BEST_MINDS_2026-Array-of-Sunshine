"""Measure how much candidate fields vary inside, to choose the demo parcel and the main index.

Reads cache/area (fetch.py --area) and candidates.geojson (polygons drawn by hand, inside each
field). For every candidate, date and index it reports:
  median        typical value of the field
  <med-0.10     share of pixels more than 0.10 below the median
  spread        robust spread of the field (1.4826 * MAD), i.e. how different pixels are
and, between 28.06 and 30.06 (two days apart, so the crop did not change):
  r             correlation of the pixel patterns of the two days; high = the pattern is real
  noise         robust spread of the day-to-day difference of each pixel
  spread/noise  how far the field's real variation stands above that noise

Indices: NDVI = (B08-B04)/(B08+B04) and EVI = 2.5(B08-B04)/(B08+6B04-7.5B02+1) at 10 m;
NDRE = (B8A-B05)/(B8A+B05) at 20 m, both bands at the same resolution.

Writes out/selection/<name>.png (rows: dates; columns: RGB, NDVI, EVI, NDRE, each index
stretched to its own 2-98 percentile range inside the field) and out/selection/measure.json.
"""
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from scipy.ndimage import distance_transform_edt

from common import HERE, OUT, load_index, ndvi, read_asset, reflectance, to_10m

REGION = "area"
CANDIDATES = HERE / "candidates.geojson"
OUT_DIR = OUT / "selection"
DROP = 0.10
INDICES = ["NDVI", "EVI", "NDRE"]
# Pixels outside the polygon with NDVI below this on the last date count as harvested / bare.
BARE_NDVI = 0.5
SCALE = 4
MARGIN_PX = 12

# Five stops of viridis: perceptually even, so contrast compares fairly between indices.
VIRIDIS = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]


def evi(blue, red, nir):
    with np.errstate(invalid="ignore", divide="ignore"):
        return 2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)


def load(scene):
    def band(asset):
        return reflectance(read_asset(REGION, scene, asset)[0][0], scene)

    red, nir, blue = band("red"), band("nir"), band("blue")
    re1, nir08 = band("rededge1"), band("nir08")
    visual, transform, crs = read_asset(REGION, scene, "visual")
    return {
        "rgb": np.moveaxis(visual, 0, -1),
        "NDVI": ndvi(red, nir),
        "EVI": evi(blue, red, nir),
        "NDRE": to_10m(ndvi(re1, nir08)),  # same normalized difference, red edge in place of red
    }, transform, crs


def robust_sd(x):
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def colorize(v, lo, hi):
    t = np.clip((v - lo) / (hi - lo), 0, 1)
    xs = np.linspace(0, 1, len(VIRIDIS))
    return np.stack([np.interp(t, xs, [c[k] for c in VIRIDIS]) for k in range(3)], -1)


def render(name, scenes, mask, ring, ranges):
    rows, cols = np.nonzero(mask)
    r0, r1 = rows.min() - MARGIN_PX, rows.max() + MARGIN_PX + 1
    c0, c1 = cols.min() - MARGIN_PX, cols.max() + MARGIN_PX + 1
    font = ImageFont.load_default(size=18)
    pts = [((x - c0) * SCALE, (y - r0) * SCALE) for x, y in ring]
    grid = []
    for date, data in scenes:
        row = []
        for kind in ["RGB"] + INDICES:
            if kind == "RGB":
                arr = data["rgb"][r0:r1, c0:c1].astype(float)
                title = f"{date} RGB"
            else:
                lo, hi = ranges[kind]
                arr = colorize(data[kind][r0:r1, c0:c1], lo, hi)
                arr[~mask[r0:r1, c0:c1]] *= 0.45  # dim everything outside the field
                title = f"{kind} {lo:.2f}-{hi:.2f}"
            img = Image.fromarray(arr.astype(np.uint8)).resize(((c1 - c0) * SCALE, (r1 - r0) * SCALE), Image.NEAREST)
            draw = ImageDraw.Draw(img)
            draw.line(pts + [pts[0]], fill=(255, 0, 255) if kind == "RGB" else (255, 255, 255), width=2)
            draw.text((6, 4), title, font=font, fill="white", stroke_width=3, stroke_fill="black")
            row.append(img)
        grid.append(row)
    w, h = grid[0][0].size
    out = Image.new("RGB", (len(grid[0]) * (w + 6), len(grid) * (h + 6)), "white")
    for i, row in enumerate(grid):
        for j, img in enumerate(row):
            out.paste(img, (j * (w + 6), i * (h + 6)))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.save(OUT_DIR / f"{name}.png")


def main():
    index = load_index(REGION)
    scenes, transform, crs = [], None, None
    for s in index["scenes"]:
        data, transform, crs = load(s)
        scenes.append((s["date"], data))
    shape = scenes[0][1]["NDVI"].shape
    dates = [d for d, _ in scenes]
    first, second, last = scenes[0][1], scenes[1][1], scenes[-1][1]

    results = {}
    for feat in json.loads(CANDIDATES.read_text(encoding="utf-8"))["features"]:
        name = feat["properties"]["name"]
        geom = transform_geom("EPSG:4326", crs, feat["geometry"])
        mask = rasterize([(geom, 1)], out_shape=shape, transform=transform, fill=0).astype(bool)
        ring = [~transform * tuple(p) for p in geom["coordinates"][0][:-1]]

        # Clearance: distance from the field pixels to the nearest bare pixel outside the polygon.
        bare_outside = (last["NDVI"] < BARE_NDVI) & ~mask
        clearance_m = 10 * distance_transform_edt(~bare_outside)[mask].min()
        bare_inside = 100 * (last["NDVI"][mask] < BARE_NDVI).mean()

        res = {"pixels": int(mask.sum()), "area_ha": round(mask.sum() / 100, 1),
               "clearance_m": round(float(clearance_m), 1), "bare_inside_last_pct": round(float(bare_inside), 2),
               "indices": {}}
        print(f"\n{name}: {mask.sum()} px = {mask.sum() / 100:.1f} ha, nearest bare pixel outside: "
              f"{clearance_m:.0f} m, bare inside on {dates[-1]}: {bare_inside:.1f}%")
        print(f"  {'index':5s} {'date':10s} {'median':>7s} {'<med-0.10':>10s} {'spread':>7s}")
        ranges = {}
        for kind in INDICES:
            per_date = []
            for date, data in scenes:
                v = data[kind][mask]
                med = float(np.median(v))
                below = 100 * float((v < med - DROP).mean())
                sd = float(robust_sd(v))
                per_date.append({"date": date, "median": round(med, 3), "below_pct": round(below, 1),
                                 "spread": round(sd, 4), "p5": round(float(np.percentile(v, 5)), 3),
                                 "p95": round(float(np.percentile(v, 95)), 3)})
                print(f"  {kind:5s} {date:10s} {med:7.3f} {below:9.1f}% {sd:7.3f}")
            a = first[kind][mask] - np.median(first[kind][mask])
            b = second[kind][mask] - np.median(second[kind][mask])
            r = float(np.corrcoef(a, b)[0, 1])
            noise = float(robust_sd(b - a) / np.sqrt(2))  # per-image noise from the difference of two
            snr = per_date[0]["spread"] / noise
            print(f"  {'':5s} {dates[0]} vs {dates[1]}: r = {r:.2f}, noise = {noise:.3f}, spread/noise = {snr:.1f}")
            res["indices"][kind] = {"per_date": per_date, "r_first_two": round(r, 3),
                                    "noise": round(noise, 4), "spread_over_noise": round(snr, 2)}
            pooled = np.concatenate([data[kind][mask] for _, data in scenes])
            ranges[kind] = tuple(np.percentile(pooled, [2, 98]))
        results[name] = res
        render(name, scenes, mask, ring, ranges)

    (OUT_DIR / "measure.json").write_text(json.dumps(results, indent=2))
    print(f"\nwritten to {OUT_DIR}")


if __name__ == "__main__":
    main()
