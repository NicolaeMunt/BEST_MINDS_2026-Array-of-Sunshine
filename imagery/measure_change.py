"""Step 7 study: comparing a scene with the previous accepted scene of the same parcel.

Only pixels valid in both scenes are compared. Rules for "this pixel got worse":
  absolute   NDVI dropped by more than 0.10 (the first idea)
  relative   NDVI dropped by more than 0.10 MORE than the parcel median dropped, i.e. the pixel's
             distance below the median grew by 0.10; a uniform change of the whole field cancels out
  new weak   weak now (step-3 rule) and not weak in the previous scene; no new threshold
Each map is cleaned like step 3 (zones under 10 pixels dropped). The whole-field change is the
difference of the two medians.

Real pairs first, then changes planted on the second scene of the first pair (2 days apart, so
nothing real changed): a new zone, uniform ripening, ripening plus a new zone, uniform growth.

    python measure_change.py 6401307.101      ->  out/<parcel>/change_study.png
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from scipy.ndimage import distance_transform_edt

from analyze import (DROP_NDVI, MIN_VALID_PCT, MIN_ZONE_PX, PIXEL_M, analyze_scene, change_since, possible_cloud,
                     remove_small_zones, weak_zones)
from common import OUT, load_parcels, study_scenes
from measure_sector import patch_at

SCALE = 3


def compare(prev, cur_ndvi, cur_valid):
    both = prev["valid"] & cur_valid
    pm = float(np.median(prev["ndvi"][prev["valid"]]))
    cm, _, cur_weak = weak_zones(cur_ndvi, cur_valid)
    _, _, prev_weak = weak_zones(prev["ndvi"], prev["valid"])
    d = cur_ndvi - prev["ndvi"]
    maps = {
        "absolute": remove_small_zones(both & (d < -DROP_NDVI), MIN_ZONE_PX),
        "relative": remove_small_zones(both & (d - (cm - pm) < -DROP_NDVI), MIN_ZONE_PX),
        "new weak": both & cur_weak & ~prev_weak,
    }
    return cm - pm, both, maps


def panel(base, valid, flagged, box, title, truth=None):
    v = base[valid]
    lo, hi = np.percentile(v, [2, 98])
    g = np.clip((np.nan_to_num(base) - lo) / (hi - lo), 0, 1) * 170 + 50
    rgb = np.stack([g, g, g], -1)
    rgb[~valid] *= 0.3
    rgb[flagged] = (230, 30, 30)
    if truth is not None:
        edge = truth & ~(np.roll(truth, 1, 0) & np.roll(truth, -1, 0) & np.roll(truth, 1, 1) & np.roll(truth, -1, 1))
        rgb[edge & ~flagged] = (40, 140, 255)
    arr = rgb[box].astype(np.uint8)
    img = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for k, line in enumerate(title):
        d.text((4, 3 + 18 * k), line, font=ImageFont.load_default(size=15), fill="white", stroke_width=3,
               stroke_fill="black")
    return img


def disk_at(valid, cy, cx, r):
    rr, cc = np.ogrid[:valid.shape[0], :valid.shape[1]]
    return valid & ((rr - cy) ** 2 + (cc - cx) ** 2 <= r * r)


def warnings_test(d0, prev, d1, cur):
    """Planted cases run through analyze.change_since and analyze.possible_cloud, the code the pipeline uses."""
    rows, cols = np.nonzero(cur["valid"])
    cy, cx = np.percentile(rows, 25), np.percentile(cols, 75)
    cloud = disk_at(cur["valid"], cy, cx, 7)                       # ~70 m radius, marked as masked
    near = disk_at(cur["valid"] & ~cloud, cy + 7 + 4 + 4, cx, 4)    # its edge ~40 m south of the cloud
    far = disk_at(cur["valid"], np.percentile(rows, 75), np.percentile(cols, 25), 4)
    dist_m = PIXEL_M * distance_transform_edt(~cloud)
    print(f"\nWarnings, planted on {d1} vs {d0} (cloud = pixels marked as masked; zones lowered by 0.20)")
    print(f"   zone next to the cloud: {near.sum()} px, nearest pixel {dist_m[near].min():.0f} m from the cloud")
    print(f"   zone far away:          {far.sum()} px, nearest pixel {dist_m[far].min():.0f} m from the cloud")

    p = {"date": d0, "ndvi": prev["ndvi"], "valid": prev["valid"],
         "median": float(np.median(prev["ndvi"][prev["valid"]]))}

    def run(name, cloud_px, zones, everywhere=0.0, date=d1):
        nd = cur["ndvi"] + everywhere
        nd[zones] -= 0.20
        valid = cur["valid"] & ~cloud_px
        c = {"ndvi": nd, "valid": valid, "invalid": cur["invalid"] | cloud_px,
             "median": float(np.median(nd[valid]))}
        change, warnings, declined = change_since(p, c, date)
        cloud = possible_cloud(weak_zones(nd, valid)[2], declined, c["invalid"])
        warnings += [cloud] if cloud else []
        shown = "; ".join(f"{w['code']}: {w['text']}" for w in warnings) or "none"
        print(f"   {name:40s} median_change {change['median_change']:+.3f}  declined {change['declined_pct']:4.1f}%  "
              f"warnings: {shown}")

    none = np.zeros_like(cloud)
    run("cloud + zone next to it + zone far away", cloud, near | far)
    run("cloud, no planted zone (a real weak zone is near)", cloud, none)
    run("zone far away, no cloud", none, far)
    run("uniform ripening (-0.15)", none, none, everywhere=-0.15)
    later = (np.datetime64(d0) + np.timedelta64(40, "D")).astype(str)
    run(f"same scene dated {later} (40 days)", none, none, date=later)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    acc = []
    for s in study_scenes(args.parcel):
        a = analyze_scene(args.parcel, parcel, s)
        if a["valid_pct"] >= MIN_VALID_PCT:
            acc.append((s["date"], a))
    rows, cols = np.nonzero(acc[0][1]["inside"])
    box = np.s_[rows.min() - 3:rows.max() + 4, cols.min() - 3:cols.max() + 4]

    print("Share of pixels flagged (% of pixels valid in both scenes), after removing zones under 10 px")
    print(f"{'pair / scenario':44s} {'median change':>13s}  {'absolute':>8s} {'relative':>8s} {'new weak':>8s}"
          f"   (planted: found in patch % / flagged outside %)")
    images = []
    for (d0, prev), (d1, cur) in zip(acc, acc[1:]):
        dm, both, maps = compare(prev, cur["ndvi"], cur["valid"])
        n = both.sum()
        print(f"{'real ' + d0 + ' -> ' + d1:44s} {dm:+13.3f}  " + " ".join(f"{100 * m.sum() / n:7.1f}%" for m in maps.values()))

    (d0, prev), (d1, cur) = acc[0], acc[1]
    patch = patch_at(cur["valid"], 25, 75, 0.10)
    scenarios = {
        "new zone NE (-0.20)": (0.0, -0.20),
        "uniform ripening (-0.15)": (-0.15, 0.0),
        "ripening (-0.15) + new zone NE (-0.20)": (-0.15, -0.20),
        "uniform growth (+0.08)": (+0.08, 0.0),
    }
    for name, (everywhere, in_patch) in scenarios.items():
        test = cur["ndvi"] + everywhere
        test[patch] += in_patch
        dm, both, maps = compare(prev, test, cur["valid"])
        cells = []
        for m in maps.values():
            if in_patch:
                cells.append(f"{100 * (m & patch).sum() / patch.sum():3.0f} / {100 * (m & both & ~patch).sum() / (both & ~patch).sum():4.1f}")
            else:
                cells.append(f"{'':4s}{100 * m.sum() / both.sum():5.1f}%")
        print(f"{'planted on ' + d1 + ': ' + name:44s} {dm:+13.3f}  " + "  ".join(f"{c:>10s}" for c in cells))
        row = [panel(test, both, maps[k], box, [name, f"{k}: {100 * maps[k].sum() / both.sum():.1f}% of parcel"],
                     truth=patch if in_patch else None) for k in maps]
        images.append(row)

    w, h = images[0][0].size
    out = Image.new("RGB", (len(images[0]) * (w + 6), len(images) * (h + 6) + 24), "white")
    for i, row in enumerate(images):
        for j, im in enumerate(row):
            out.paste(im, (j * (w + 6), i * (h + 6)))
    ImageDraw.Draw(out).text((6, out.height - 20), "red: flagged as got worse   blue: edge of the planted zone "
                             "(where not flagged)   grey: NDVI of the second scene", fill="black",
                             font=ImageFont.load_default(size=15))
    path = OUT / args.parcel / "change_study.png"
    out.save(path)
    print(f"\nwritten {path}")
    warnings_test(d0, prev, d1, cur)


if __name__ == "__main__":
    main()
