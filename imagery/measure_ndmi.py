"""Step 8 study: what NDMI adds to NDVI on this parcel, before deciding how to use it.

NDMI = (B8A - B11) / (B8A + B11), both at 20 m: water in the leaves (not in the soil).
For the accepted scenes, on 20 m pixels fully inside the valid shrunken parcel:
  1. NDMI per date: median, spread; day-to-day noise and repeatability (first two dates)
  2. how tightly NDMI follows NDVI inside the field (correlation, slope of NDMI on NDVI)
  3. for every weak zone of the pipeline: its NDVI and NDMI below the parcel median, the NDMI drop
     that the NDVI drop alone predicts (slope x NDVI drop), and how many distinct 20 m pixels it has

    python measure_ndmi.py 6401307.101      ->  out/<parcel>/ndmi_study.png
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label

from analyze import MIN_VALID_PCT, analyze_scene, weak_zones
from common import OUT, load_parcels, ndvi, read_asset, reflectance, study_scenes, to_10m


def robust_sd(x):
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def blocks20(a10):
    """10 m array -> 20 m (2 x 2 blocks): mean for numbers, all() for masks."""
    h, w = a10.shape[0] // 2 * 2, a10.shape[1] // 2 * 2
    b = a10[:h, :w].reshape(h // 2, 2, w // 2, 2)
    return b.all(axis=(1, 3)) if a10.dtype == bool else b.mean(axis=(1, 3))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    data = []
    for s in study_scenes(args.parcel):
        a = analyze_scene(args.parcel, parcel, s)
        if a["valid_pct"] < MIN_VALID_PCT:
            continue
        ndmi20 = ndvi(reflectance(read_asset(args.parcel, s, "swir16")[0][0], s),
                      reflectance(read_asset(args.parcel, s, "nir08")[0][0], s))  # (nir08 - swir16) / (nir08 + swir16)
        med, _, weak = weak_zones(a["ndvi"], a["valid"])
        data.append((s["date"], a, ndmi20, med, weak))

    print("1-2. NDMI on 20 m pixels fully inside the valid parcel")
    slopes = {}
    for date, a, ndmi20, med, weak in data:
        ok = blocks20(a["valid"])
        m, v = ndmi20[:ok.shape[0], :ok.shape[1]][ok], blocks20(a["ndvi"])[ok]
        slope, _ = np.polyfit(v, m, 1)
        slopes[date] = slope
        print(f"   {date}: {ok.sum()} px  NDMI median {np.median(m):.3f}  spread {robust_sd(m):.3f}   "
              f"NDVI-NDMI correlation {np.corrcoef(v, m)[0, 1]:.2f}, slope {slope:.2f}")
    (d0, a0, n0, *_), (d1, a1, n1, *_) = data[0], data[1]
    ok = blocks20(a0["valid"]) & blocks20(a1["valid"])
    x, y = n0[:ok.shape[0], :ok.shape[1]][ok], n1[:ok.shape[0], :ok.shape[1]][ok]
    ax, ay = x - np.median(x), y - np.median(y)
    print(f"   {d0} vs {d1}: pattern repeats r = {np.corrcoef(ax, ay)[0, 1]:.2f}, "
          f"noise {robust_sd(ay - ax) / np.sqrt(2):.3f}, spread/noise {robust_sd(x) / (robust_sd(ay - ax) / np.sqrt(2)):.1f}")

    print("\n3. Weak zones: how far below the parcel median (NDVI, NDMI), and the NDMI drop NDVI alone predicts")
    for date, a, ndmi20, med, weak in data:
        ndmi10 = to_10m(ndmi20)[:a["ndvi"].shape[0], :a["ndvi"].shape[1]]
        ndmi_med = np.median(ndmi10[a["valid"]])
        labels, n = label(weak, structure=np.ones((3, 3), bool))
        if n == 0:
            print(f"   {date}: no weak zone")
        for k in range(1, n + 1):
            z = labels == k
            rows, cols = np.nonzero(z)
            n20 = len(set(zip(rows // 2, cols // 2)))
            dv = np.median(a["ndvi"][z]) - med
            dm = np.median(ndmi10[z]) - ndmi_med
            print(f"   {date} zone {k}: {z.sum():3d} px (= {n20} distinct 20 m pixels)  NDVI {dv:+.3f}  NDMI {dm:+.3f}  "
                  f"predicted from NDVI {slopes[date] * dv:+.3f}  difference {dm - slopes[date] * dv:+.3f}")

    # Picture: NDVI and NDMI side by side per date, each stretched inside the parcel, weak zones outlined.
    scale, font = 3, ImageFont.load_default(size=15)
    rows_img = []
    rr, cc = np.nonzero(data[0][1]["inside"])
    box = np.s_[rr.min() - 3:rr.max() + 4, cc.min() - 3:cc.max() + 4]
    for date, a, ndmi20, med, weak in data:
        ndmi10 = to_10m(ndmi20)[:a["ndvi"].shape[0], :a["ndvi"].shape[1]]
        row = []
        for name, arr in [("NDVI 10 m", a["ndvi"]), ("NDMI 20 m", ndmi10)]:
            lo, hi = np.percentile(arr[a["valid"]], [2, 98])
            g = np.clip((np.nan_to_num(arr) - lo) / (hi - lo), 0, 1) * 200 + 40
            rgb = np.stack([g, g, g], -1)
            rgb[~a["valid"]] *= 0.3
            edge = weak & ~(np.roll(weak, 1, 0) & np.roll(weak, -1, 0) & np.roll(weak, 1, 1) & np.roll(weak, -1, 1))
            rgb[edge] = (230, 30, 30)
            img = Image.fromarray(rgb[box].astype(np.uint8))
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
            ImageDraw.Draw(img).text((4, 3), f"{date} {name} ({lo:.2f}-{hi:.2f})", font=font, fill="white",
                                     stroke_width=3, stroke_fill="black")
            row.append(img)
        rows_img.append(row)
    w, h = rows_img[0][0].size
    out = Image.new("RGB", (2 * (w + 6), len(rows_img) * (h + 6)), "white")
    for i, row in enumerate(rows_img):
        for j, im in enumerate(row):
            out.paste(im, (j * (w + 6), i * (h + 6)))
    path = OUT / args.parcel / "ndmi_study.png"
    out.save(path)
    print(f"\nwritten {path}  (light = higher; red = outline of the NDVI weak zones)")


if __name__ == "__main__":
    main()
