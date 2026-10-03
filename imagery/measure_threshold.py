"""Measurements behind step 3: which pixels count as weak, and how isolated ones are cleaned.

Uses the same mask and shrink as analyze.py, on the parcel's accepted scenes.
  1. NDVI distribution per date: median, robust spread, percentiles; histogram image.
  2. Share of weak pixels for each candidate rule, with each cleanup option.
  3. Planted-patch test (known answer): on a copy of the first scene, NDVI is lowered by a fixed
     amount inside a patch covering 10% or 30% of the parcel (the pixels nearest to a point in the
     north-east). For each rule: how much of the patch is found, how much is flagged outside it.
     The patch exists only here; nothing synthetic reaches out/imagery.json.

    python measure_threshold.py demo1
Writes out/<parcel>/threshold_hist.png, threshold_rules.png, threshold_cleanup.png, threshold_planted.png.
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_opening

from analyze import MIN_VALID_PCT, MIN_ZONE_PX, analyze_scene, remove_small_zones as remove_small
from common import OUT, load_index, load_parcels

RULES = {
    "fixed 0.15": lambda v, med, sd: v < med - 0.15,
    "fixed 0.10": lambda v, med, sd: v < med - 0.10,
    "relative 15%": lambda v, med, sd: v < med * 0.85,
    "MAD 3 sd (min 0.05)": lambda v, med, sd: v < med - max(3 * sd, 0.05),
}
CLEANUPS = {
    "none": lambda weak: weak,
    f"zones < {MIN_ZONE_PX} px removed": lambda weak: remove_small(weak, MIN_ZONE_PX),
    "opening 3x3": lambda weak: binary_opening(weak, structure=np.ones((3, 3), bool)),
}
PATCH_SHARES = [0.10, 0.30]
PATCH_DEFICITS = [0.12, 0.20]
SCALE = 3


def robust_sd(x):
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def weak_map(rule, ndvi_map, valid):
    v = ndvi_map[valid]
    med, sd = float(np.median(v)), float(robust_sd(v))
    weak = np.zeros_like(valid)
    weak[valid] = rule(v, med, sd)
    return weak, med, sd


def planted_patch(valid, share):
    """The `share` of valid pixels nearest to a point in the north-east of the parcel."""
    rows, cols = np.nonzero(valid)
    cy, cx = np.percentile(rows, 25), np.percentile(cols, 75)
    order = np.argsort((rows - cy) ** 2 + (cols - cx) ** 2)[: int(round(share * len(rows)))]
    patch = np.zeros_like(valid)
    patch[rows[order], cols[order]] = True
    return patch


def crop_box(mask, margin=4):
    rows, cols = np.nonzero(mask)
    return slice(rows.min() - margin, rows.max() + margin + 1), slice(cols.min() - margin, cols.max() + margin + 1)


def panel(ndvi_map, valid, weak, box, title, outline=None):
    """Grey NDVI (stretched inside the parcel), weak pixels red, outside the parcel dark."""
    v = ndvi_map[valid]
    lo, hi = np.percentile(v, [2, 98])
    g = np.clip((np.nan_to_num(ndvi_map) - lo) / (hi - lo), 0, 1) * 200 + 40
    rgb = np.stack([g, g, g], -1)
    rgb[~valid] *= 0.25
    rgb[weak] = (230, 30, 30)
    if outline is not None:
        edge = outline & ~binary_opening(outline, structure=np.ones((3, 3), bool))
        rgb[edge & ~weak] = (40, 140, 255)
    arr = rgb[box].astype(np.uint8)
    img = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    for k, line in enumerate(title):
        draw.text((5, 3 + 19 * k), line, font=ImageFont.load_default(size=16), fill="white", stroke_width=3,
                  stroke_fill="black")
    return img


def grid(rows_of_images, path):
    w, h = rows_of_images[0][0].size
    out = Image.new("RGB", (len(rows_of_images[0]) * (w + 6), len(rows_of_images) * (h + 6)), "white")
    for i, row in enumerate(rows_of_images):
        for j, img in enumerate(row):
            out.paste(img, (j * (w + 6), i * (h + 6)))
    out.save(path)


def histogram(per_date, path):
    """NDVI histogram per date, with the threshold of every rule marked."""
    w, h, pad = 520, 260, 30
    lo, hi, step = 0.45, 0.95, 0.01
    font = ImageFont.load_default(size=14)
    colors = {"median": (0, 0, 0), "fixed 0.15": (200, 0, 0), "fixed 0.10": (240, 140, 0),
              "relative 15%": (0, 90, 220), "MAD 3 sd (min 0.05)": (150, 0, 170)}
    out = Image.new("RGB", (len(per_date) * (w + 10), h + 3 * pad + 18 * len(colors)), "white")
    for k, (date, v) in enumerate(per_date):
        img = Image.new("RGB", (w, h + 2 * pad), "white")
        d = ImageDraw.Draw(img)
        counts, edges = np.histogram(v, bins=np.arange(lo, hi + step, step))
        share = counts / len(v)
        x = lambda val: pad + (val - lo) / (hi - lo) * (w - 2 * pad)
        y = lambda frac: h + pad - frac / max(share.max(), 1e-9) * (h - pad)
        for c, e in zip(share, edges[:-1]):
            d.rectangle([x(e), y(c), x(e + step) - 1, h + pad], fill=(170, 170, 170))
        med, sd = float(np.median(v)), float(robust_sd(v))
        marks = {"median": med, "fixed 0.15": med - 0.15, "fixed 0.10": med - 0.10, "relative 15%": med * 0.85,
                 "MAD 3 sd (min 0.05)": med - max(3 * sd, 0.05)}
        for name, val in marks.items():
            d.line([(x(val), pad), (x(val), h + pad)], fill=colors[name], width=2)
        for t in np.arange(0.5, 0.95, 0.1):
            d.text((x(t), h + pad + 4), f"{t:.1f}", font=font, fill="black", anchor="mt")
        d.text((pad, 6), f"{date}  NDVI, {len(v)} px", font=font, fill="black")
        out.paste(img, (k * (w + 10), 0))
    d = ImageDraw.Draw(out)
    for i, (name, col) in enumerate(colors.items()):
        yy = h + 2 * pad + 10 + 18 * i
        d.line([(10, yy + 7), (40, yy + 7)], fill=col, width=3)
        d.text((48, yy), name if name == "median" else f"threshold: {name}", font=font, fill="black")
    out.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    out_dir = OUT / args.parcel
    scenes = []
    for scene in load_index(args.parcel)["scenes"]:
        a = analyze_scene(args.parcel, parcel, scene)
        if a["valid_pct"] >= MIN_VALID_PCT:
            scenes.append((scene["date"], a))
    box = crop_box(scenes[0][1]["inside"])

    print("1. NDVI inside the parcel (valid pixels after mask and shrink)")
    for date, a in scenes:
        v = a["ndvi"][a["valid"]]
        p = np.percentile(v, [1, 5, 50, 95])
        print(f"   {date}: {len(v)} px  median {np.median(v):.3f}  robust sd {robust_sd(v):.3f}  "
              f"p1 {p[0]:.3f}  p5 {p[1]:.3f}  p95 {p[3]:.3f}")
    histogram([(d, a["ndvi"][a["valid"]]) for d, a in scenes], out_dir / "threshold_hist.png")

    print("\n2. Share of weak pixels (% of valid pixels): " + " | ".join(CLEANUPS))
    rule_rows = []
    for name, rule in RULES.items():
        cells, row = [], []
        for date, a in scenes:
            weak, med, sd = weak_map(rule, a["ndvi"], a["valid"])
            n = a["valid"].sum()
            cells.append(f"{date[5:]}: " + " / ".join(f"{100 * c(weak).sum() / n:4.1f}" for c in CLEANUPS.values()))
            row.append(panel(a["ndvi"], a["valid"], weak, box, [name, f"{date}  {100 * weak.sum() / n:.1f}%"]))
        print(f"   {name:20s} " + "   ".join(cells))
        rule_rows.append(row)
    grid(rule_rows, out_dir / "threshold_rules.png")

    date0, a0 = scenes[0]
    weak0, _, _ = weak_map(RULES["fixed 0.10"], a0["ndvi"], a0["valid"])
    n0 = a0["valid"].sum()
    grid([[panel(a0["ndvi"], a0["valid"], c(weak0), box, [f"fixed 0.10, {date0}", f"{cname}: {100 * c(weak0).sum() / n0:.1f}%"])
           for cname, c in CLEANUPS.items()]], out_dir / "threshold_cleanup.png")

    print(f"\n3. Planted patch on {date0}: found in patch % / flagged outside patch %  (no cleanup | zones < {MIN_ZONE_PX} px removed)")
    planted_rows = []
    for name, rule in RULES.items():
        cells, row = [], []
        for share in PATCH_SHARES:
            patch = planted_patch(a0["valid"], share)
            for deficit in PATCH_DEFICITS:
                test = a0["ndvi"].copy()
                test[patch] -= deficit
                weak, med, sd = weak_map(rule, test, a0["valid"])
                clean = remove_small(weak, MIN_ZONE_PX)
                outside = a0["valid"] & ~patch
                stats = [(100 * (w & patch).sum() / patch.sum(), 100 * (w & outside).sum() / outside.sum())
                         for w in (weak, clean)]
                cells.append(f"{int(share * 100)}% -{deficit:.2f}: " + " | ".join(f"{f:5.1f} / {o:4.1f}" for f, o in stats))
                row.append(panel(test, a0["valid"], weak, box,
                                 [name, f"patch {int(share * 100)}%, -{deficit:.2f}",
                                  f"found {stats[0][0]:.0f}%, outside {stats[0][1]:.1f}%"], outline=patch))
        print(f"   {name:20s} " + "   ".join(cells))
        planted_rows.append(row)
    grid(planted_rows, out_dir / "threshold_planted.png")
    print(f"\nwritten to {out_dir}: threshold_hist.png, threshold_rules.png, threshold_cleanup.png, threshold_planted.png")


if __name__ == "__main__":
    main()
