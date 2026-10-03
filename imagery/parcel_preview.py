"""Look at the cached windows of one parcel, before any analysis.

For every cached date: true colour, the SCL class map and raw NDVI, each with the parcel outline.
Also prints the share of each SCL class inside the polygon.

    python parcel_preview.py 6401307.101     ->  out/<parcel>/preview.png
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import OUT, colorize_ndvi, load_index, load_parcels, ndvi, polygon_mask, polygon_pixels, read_asset, \
    reflectance, to_10m

SCALE = 4

# Sentinel-2 scene classification (SCL) classes with ESA's usual colours.
SCL_CLASSES = {
    0: ("no data", (0, 0, 0)),
    1: ("saturated", (255, 0, 0)),
    2: ("dark area", (47, 47, 47)),
    3: ("cloud shadow", (100, 50, 0)),
    4: ("vegetation", (0, 160, 0)),
    5: ("bare soil", (255, 230, 90)),
    6: ("water", (0, 0, 255)),
    7: ("unclassified", (128, 128, 128)),
    8: ("cloud medium", (192, 192, 192)),
    9: ("cloud high", (255, 255, 255)),
    10: ("thin cirrus", (100, 200, 255)),
    11: ("snow", (255, 150, 255)),
}


def colorize_scl(scl):
    rgb = np.zeros(scl.shape + (3,), np.uint8)
    for k, (_, color) in SCL_CLASSES.items():
        rgb[scl == k] = color
    return rgb


def panel(arr, ring, title):
    img = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    draw.line([(x * SCALE, y * SCALE) for x, y in ring], fill=(255, 0, 255), width=2)
    draw.text((6, 4), title, font=ImageFont.load_default(size=18), fill="white", stroke_width=3, stroke_fill="black")
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    args = ap.parse_args()
    parcel = load_parcels()[args.parcel]
    rows = []
    for scene in load_index(args.parcel)["scenes"]:
        if not scene.get("bands_downloaded", True):
            continue  # too cloudy over the parcel, only SCL was downloaded
        visual, transform, crs = read_asset(args.parcel, scene, "visual")
        red = reflectance(read_asset(args.parcel, scene, "red")[0][0], scene)
        nir = reflectance(read_asset(args.parcel, scene, "nir")[0][0], scene)
        scl = to_10m(read_asset(args.parcel, scene, "scl")[0][0])
        mask = polygon_mask(parcel["geometry"], transform, crs, scl.shape)
        ring = polygon_pixels(parcel["geometry"], transform, crs)

        inside = scl[mask]
        shares = {SCL_CLASSES[k][0]: 100 * (inside == k).mean() for k in SCL_CLASSES if (inside == k).any()}
        print(f"{scene['date']} {scene['item_id']}  {mask.sum()} px inside:  "
              + ", ".join(f"{name} {pct:.1f}%" for name, pct in shares.items()))

        rows.append([
            panel(np.moveaxis(visual, 0, -1), ring, f"{scene['date']} RGB"),
            panel(colorize_scl(scl), ring, "SCL"),
            panel(colorize_ndvi(ndvi(red, nir)), ring, "NDVI (no mask)"),
        ])

    w, h = rows[0][0].size
    legend_h = 26 * ((len(SCL_CLASSES) + 3) // 4) + 10
    out = Image.new("RGB", (3 * (w + 6), len(rows) * (h + 6) + legend_h), "white")
    for i, row in enumerate(rows):
        for j, img in enumerate(row):
            out.paste(img, (j * (w + 6), i * (h + 6)))
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=16)
    y0 = len(rows) * (h + 6) + 6
    for n, (k, (name, color)) in enumerate(SCL_CLASSES.items()):
        x, y = (n % 4) * 220 + 8, y0 + (n // 4) * 26
        draw.rectangle([x, y, x + 18, y + 18], fill=color, outline=(0, 0, 0))
        draw.text((x + 26, y), f"{k} {name}", font=font, fill="black")
    path = OUT / args.parcel / "preview.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    print(f"written {path}")


if __name__ == "__main__":
    main()
