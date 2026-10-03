"""Measurements behind step 4: how to name where the weak zones are, and what to do with several.

Sectors: the box around the shrunken parcel is cut into 3 x 3 equal cells, north up:
    NW N NE / W C E / SW S SE
A second way of naming: the compass direction from the parcel centre to a point, rounded to one of
8 directions, or C when the point is within analyze.CENTRE_FRACTION of the parcel's radius from the centre.
Three ways to pick the point or cell:
    A  the cell of the centroid of all weak pixels
    B  the cell of the centroid of the largest zone; the other zones are only counted
    C  the cell holding the largest share of the weak area (top three shares are printed)
Scenarios: the real accepted dates, and patches planted at known places on a copy of the first
scene (lowered by 0.20, so every patch is surely weak). Weak zones come from analyze.py exactly
as in the pipeline. Nothing planted reaches out/imagery.json.

    python measure_sector.py demo1      ->  out/<parcel>/sector_study.png
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label

from analyze import MIN_VALID_PCT, analyze_scene, direction_of, weak_zones
from common import OUT, load_index, load_parcels

NAMES = [["NW", "N", "NE"], ["W", "C", "E"], ["SW", "S", "SE"]]
DEFICIT = 0.20
SCALE = 3


def patch_at(valid, row_pct, col_pct, share):
    """The `share` of valid pixels nearest to the point at the given row/column percentiles."""
    rows, cols = np.nonzero(valid)
    cy, cx = np.percentile(rows, row_pct), np.percentile(cols, col_pct)
    order = np.argsort((rows - cy) ** 2 + (cols - cx) ** 2)[: int(round(share * len(rows)))]
    patch = np.zeros_like(valid)
    patch[rows[order], cols[order]] = True
    return patch


def cell_of(row, col, box):
    r0, r1, c0, c1 = box
    i = min(int(3 * (row - r0) / (r1 - r0 + 1)), 2)
    j = min(int(3 * (col - c0) / (c1 - c0 + 1)), 2)
    return NAMES[i][j]


def sectors(weak, box):
    labels, n = label(weak, structure=np.ones((3, 3), bool))
    if n == 0:
        return None
    rows, cols = np.nonzero(weak)
    a = cell_of(rows.mean(), cols.mean(), box)
    sizes = np.bincount(labels.ravel())[1:]
    big = np.argmax(sizes) + 1
    br, bc = np.nonzero(labels == big)
    b = cell_of(br.mean(), bc.mean(), box)
    per_cell = {}
    for r, c in zip(rows, cols):
        name = cell_of(r, c, box)
        per_cell[name] = per_cell.get(name, 0) + 1
    shares = sorted(((100 * v / len(rows), k) for k, v in per_cell.items()), reverse=True)
    return {"zones": sorted(sizes.tolist(), reverse=True), "A": a, "B": b, "C": shares[:3],
            "largest_share": 100 * sizes.max() / len(rows),
            "centroid_all": (rows.mean(), cols.mean()), "centroid_big": (br.mean(), bc.mean()), "labels": labels,
            "big": big}


def panel(ndvi_map, valid, weak, box, res, title):
    v = ndvi_map[valid]
    lo, hi = np.percentile(v, [2, 98])
    g = np.clip((np.nan_to_num(ndvi_map) - lo) / (hi - lo), 0, 1) * 170 + 50
    rgb = np.stack([g, g, g], -1)
    rgb[~valid] *= 0.3
    if res:
        rgb[weak] = (255, 150, 0)
        rgb[res["labels"] == res["big"]] = (230, 30, 30)
    r0, r1, c0, c1 = box
    sl = np.s_[r0 - 4:r1 + 5, c0 - 4:c1 + 5]
    arr = rgb[sl].astype(np.uint8)
    img = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    d = ImageDraw.Draw(img)
    to_px = lambda r, c: ((c - (c0 - 4)) * SCALE, (r - (r0 - 4)) * SCALE)
    for k in range(4):
        x = c0 + k * (c1 - c0 + 1) / 3
        y = r0 + k * (r1 - r0 + 1) / 3
        d.line([to_px(r0, x), to_px(r1 + 1, x)], fill=(0, 200, 255), width=1)
        d.line([to_px(y, c0), to_px(y, c1 + 1)], fill=(0, 200, 255), width=1)
    for i in range(3):
        for j in range(3):
            d.text(to_px(r0 + (i + 0.5) * (r1 - r0 + 1) / 3, c0 + (j + 0.5) * (c1 - c0 + 1) / 3), NAMES[i][j],
                   font=ImageFont.load_default(size=14), fill=(0, 200, 255), anchor="mm")
    if res:
        for (r, c), col in [(res["centroid_all"], "white"), (res["centroid_big"], (255, 255, 0))]:
            x, y = to_px(r, c)
            d.line([(x - 7, y - 7), (x + 7, y + 7)], fill=col, width=3)
            d.line([(x - 7, y + 7), (x + 7, y - 7)], fill=col, width=3)
    for k, line in enumerate(title):
        d.text((4, 3 + 18 * k), line, font=ImageFont.load_default(size=15), fill="white", stroke_width=3,
               stroke_fill="black")
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    accepted = []
    for scene in load_index(args.parcel)["scenes"]:
        a = analyze_scene(args.parcel, parcel, scene)
        if a["valid_pct"] >= MIN_VALID_PCT:
            accepted.append((scene["date"], a))
    rows, cols = np.nonzero(accepted[0][1]["inner"])
    box = (rows.min(), rows.max(), cols.min(), cols.max())
    centre, radius = (rows.mean(), cols.mean()), np.sqrt(len(rows) / np.pi)

    date0, a0 = accepted[0]
    valid0 = a0["valid"]
    planted = {
        "1 patch NE, 10%": [(25, 75, 0.10)],
        "1 patch NE, 30%": [(25, 75, 0.30)],
        "1 patch centre, 10%": [(50, 50, 0.10)],
        "2 patches: NE 10% + SW 5%": [(25, 75, 0.10), (75, 25, 0.05)],
        "4 small patches, 1% each": [(15, 50, 0.01), (50, 15, 0.01), (50, 85, 0.01), (85, 50, 0.01)],
    }
    scenarios = [(f"real {d}", a["ndvi"], a["valid"]) for d, a in accepted]
    for name, spots in planted.items():
        test = a0["ndvi"].copy()
        for rp, cp, share in spots:
            test[patch_at(valid0, rp, cp, share)] -= DEFICIT
        scenarios.append((f"planted: {name}", test, valid0))

    print(f"{'':38s} {'':8s}  {'':22s} {'3x3 grid':^21s}            {'direction':^13s}  largest zone")
    print(f"{'scenario':38s} {'affected':>8s}  {'zones (px)':22s} {'A cent.':>7s} {'B larg.':>7s}  C shares"
          f"{'':12s}{'A':>4s} {'B':>4s}  share of weak")
    images = []
    for name, ndvi_map, valid in scenarios:
        median, raw, weak = weak_zones(ndvi_map, valid)
        affected = 100 * weak.sum() / valid.sum()
        res = sectors(weak, box)
        if res is None:
            print(f"{name:38s} {affected:7.1f}%  {'none':22s} {'-':>10s} {'-':>9s}   -")
            title = [name, f"affected {affected:.1f}%, no zone"]
        else:
            shares = ", ".join(f"{k} {s:.0f}%" for s, k in res["C"])
            da = direction_of(*res["centroid_all"], centre, radius)
            db = direction_of(*res["centroid_big"], centre, radius)
            print(f"{name:38s} {affected:7.1f}%  {str(res['zones'][:5]):22s} {res['A']:>7s} {res['B']:>7s}  "
                  f"{shares:20s}{da:>4s} {db:>4s}  {res['largest_share']:5.0f}%")
            title = [name, f"affected {affected:.1f}%, {len(res['zones'])} zone(s)",
                     f"grid: A {res['A']} | B {res['B']} | C {res['C'][0][1]}",
                     f"direction: A {da} | B {db}"]
        images.append(panel(ndvi_map, valid, weak, box, res, title))

    cols_n = 4
    w, h = images[0].size
    out = Image.new("RGB", (cols_n * (w + 6), ((len(images) + cols_n - 1) // cols_n) * (h + 6) + 26), "white")
    for i, img in enumerate(images):
        out.paste(img, ((i % cols_n) * (w + 6), (i // cols_n) * (h + 6)))
    ImageDraw.Draw(out).text(
        (6, out.height - 22), "red: largest zone  orange: other zones  white X: centroid of all weak pixels (A)  "
        "yellow X: centroid of the largest zone (B)  cyan: 3x3 sectors", font=ImageFont.load_default(size=15),
        fill="black")
    path = OUT / args.parcel / "sector_study.png"
    out.save(path)
    print(f"\nwritten {path}")


if __name__ == "__main__":
    main()
