"""Overview images of the zone around Orhei, used only to choose the demo parcel.

Reads cache/area (run `python fetch.py --area` first) and writes to out/area/:
  <date>.png      true colour | NDVI, side by side
  ndvi_dates.png  NDVI of every date side by side, to spot fields that change
Every image has a 1 km grid labelled A1, B1, ... (columns are letters, rows numbers).

    python area_preview.py              # the overview images
    python area_preview.py --zoom C2    # 2 x 2 km from cell C2, enlarged, 250 m grid
"""
import argparse
import string

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import OUT, colorize_ndvi, load_index, ndvi, read_asset, reflectance, to_10m

REGION = "area"
CELL_PX = 100  # 1 km at 10 m
SCL_UNUSABLE = [0, 1, 3, 8, 9, 10, 11]

def with_grid(rgb, title):
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=15)
    h, w = rgb.shape[:2]
    for x in range(0, w, CELL_PX):
        draw.line([(x, 0), (x, h)], fill=(255, 255, 255), width=1)
    for y in range(0, h, CELL_PX):
        draw.line([(0, y), (w, y)], fill=(255, 255, 255), width=1)
    for i, x in enumerate(range(0, w, CELL_PX)):
        for j, y in enumerate(range(0, h, CELL_PX)):
            draw.text((x + 3, y + 2), f"{string.ascii_uppercase[i]}{j + 1}", font=font,
                      fill="white", stroke_width=2, stroke_fill="black")
    big = ImageFont.load_default(size=28)
    draw.text((w - 10, h - 10), title, font=big, anchor="rd", fill="white", stroke_width=3, stroke_fill="black")
    return img


def side_by_side(images, gap=12):
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    out = Image.new("RGB", (w, max(i.height for i in images)), "white")
    x = 0
    for i in images:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def load_scene(scene):
    visual, _, _ = read_asset(REGION, scene, "visual")
    red = reflectance(read_asset(REGION, scene, "red")[0][0], scene)
    nir = reflectance(read_asset(REGION, scene, "nir")[0][0], scene)
    scl = to_10m(read_asset(REGION, scene, "scl")[0][0])
    return np.moveaxis(visual, 0, -1), ndvi(red, nir), np.isin(scl, SCL_UNUSABLE)


def zoom(cell, cells, scale=3, sub_px=25):
    """Enlarged crop starting at a grid cell: RGB on the top row, NDVI below, one column per date.
    Thin lines every 250 m; edge labels are pixel coordinates in the area window."""
    x0 = string.ascii_uppercase.index(cell[0].upper()) * CELL_PX
    y0 = (int(cell[1:]) - 1) * CELL_PX
    size = cells * CELL_PX
    font = ImageFont.load_default(size=14)
    big = ImageFont.load_default(size=22)
    rows = [[], []]
    for scene in load_index(REGION)["scenes"]:
        rgb, v, unusable = load_scene(scene)
        crop = np.s_[y0:y0 + size, x0:x0 + size]
        for r, (arr, kind) in enumerate([(rgb[crop], "RGB"), (colorize_ndvi(v[crop], unusable[crop]), "NDVI")]):
            img = Image.fromarray(arr).resize((arr.shape[1] * scale, arr.shape[0] * scale), Image.NEAREST)
            draw = ImageDraw.Draw(img)
            for k in range(0, size + 1, sub_px):
                strong = (x0 + k) % CELL_PX == 0
                width = 2 if strong else 1
                draw.line([(k * scale, 0), (k * scale, img.height)], fill="white", width=width)
                draw.line([(0, k * scale), (img.width, k * scale)], fill="white", width=width)
                if k % (2 * sub_px) == 0:
                    draw.text((k * scale + 2, img.height - 2), str(x0 + k), font=font, anchor="ld",
                              fill="white", stroke_width=2, stroke_fill="black")
                    draw.text((img.width - 2, k * scale + 2), str(y0 + k), font=font, anchor="rt",
                              fill="white", stroke_width=2, stroke_fill="black")
            draw.text((8, 8), f"{scene['date']} {kind}", font=big, fill="white", stroke_width=3, stroke_fill="black")
            rows[r].append(img)
    top, bottom = side_by_side(rows[0]), side_by_side(rows[1])
    out = Image.new("RGB", (top.width, top.height * 2 + 12), "white")
    out.paste(top, (0, 0))
    out.paste(bottom, (0, top.height + 12))
    path = OUT / "area" / f"zoom_{cell.upper()}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    print(f"written {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zoom", metavar="CELL", help="grid cell where the enlarged crop starts, e.g. C2")
    ap.add_argument("--cells", type=int, default=2, help="crop size in 1 km cells (default 2)")
    args = ap.parse_args()
    if args.zoom:
        zoom(args.zoom, args.cells)
        return

    index = load_index(REGION)
    out_dir = OUT / "area"
    out_dir.mkdir(parents=True, exist_ok=True)
    ndvi_tiles = []
    for scene in index["scenes"]:
        date = scene["date"]
        visual, v, unusable = load_scene(scene)
        scl = to_10m(read_asset(REGION, scene, "scl")[0][0])

        rgb_img = with_grid(visual, f"{date}  RGB")
        ndvi_img = with_grid(colorize_ndvi(v, unusable), f"{date}  NDVI")
        side_by_side([rgb_img, ndvi_img]).save(out_dir / f"{date}.png")
        ndvi_tiles.append(ndvi_img)

        classes = {"vegetation": [4], "bare soil": [5], "water": [6], "unusable": SCL_UNUSABLE}
        shares = "  ".join(f"{k} {100 * np.isin(scl, c).mean():.1f}%" for k, c in classes.items())
        veg = scl == 4
        print(f"{date}  {v.shape[1]}x{v.shape[0]} px  {shares}  "
              f"NDVI median: vegetation {np.nanmedian(v[veg]):.2f}, all usable {np.nanmedian(v[~unusable]):.2f}")
    side_by_side(ndvi_tiles).save(out_dir / "ndvi_dates.png")
    print(f"written to {out_dir}")


if __name__ == "__main__":
    main()
