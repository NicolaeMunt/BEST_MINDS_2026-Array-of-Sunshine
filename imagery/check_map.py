"""Check what the map will show, using only what the frontend receives.

Places photo and overlay the way Leaflet does (longitude linear, latitude in Web Mercator, between
overlay_bounds), then draws the parcel polygon and zone_center from the JSON on top. If the images
were misplaced, the outline would not sit on the field and the marker would miss the red zone.
Also checks automatically that zone_center falls on a red overlay pixel.

    python check_map.py      ->  out/<parcel>/map_check.png
"""
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from analyze import OUTPUT, WEAK_RGBA
from common import OUT, load_parcels


def mercator_y(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def to_pixel(lon, lat, bounds, width, height):
    south, west, north, east = bounds
    x = (lon - west) / (east - west) * width
    y = (mercator_y(north) - mercator_y(lat)) / (mercator_y(north) - mercator_y(south)) * height
    return x, y


def main():
    parcels = load_parcels()
    results = json.loads(OUTPUT.read_text(encoding="utf-8"))["results"]
    by_parcel = {}
    for r in results:
        photo = Image.open(OUT / r["photo_path"].lstrip("/")).convert("RGBA")
        overlay = Image.open(OUT / r["overlay_path"].lstrip("/")).convert("RGBA")
        assert photo.size == overlay.size, (photo.size, overlay.size)
        w, h = photo.size
        img = Image.alpha_composite(photo, overlay)
        draw = ImageDraw.Draw(img)
        ring = parcels[r["parcel_id"]]["geometry"]["coordinates"][0]
        draw.line([to_pixel(lon, lat, r["overlay_bounds"], w, h) for lon, lat in ring], fill=(255, 0, 255), width=3)
        status = "no zone"
        if r["zone_center"]:
            x, y = to_pixel(*r["zone_center"], r["overlay_bounds"], w, h)
            hit = tuple(np.asarray(overlay)[int(y), int(x)]) == WEAK_RGBA
            status = f"zone_center on red: {'YES' if hit else 'NO'}"
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(255, 255, 0), width=3)
        print(f"{r['parcel_id']} {r['scene_date']}: {w} x {h} px, {status}")
        for k, line in enumerate([r["scene_date"], f"{r['affected_pct']}% {r['affected_sector']}", status]):
            draw.text((8, 6 + 24 * k), line, font=ImageFont.load_default(size=20), fill="white", stroke_width=3,
                      stroke_fill="black")
        by_parcel.setdefault(r["parcel_id"], []).append(img.convert("RGB"))
    for pid, images in by_parcel.items():
        w, h = images[0].size
        sheet = Image.new("RGB", (len(images) * (w + 8), h), "white")
        for i, im in enumerate(images):
            sheet.paste(im, (i * (w + 8), 0))
        sheet = sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS)
        path = OUT / pid / "map_check.png"
        sheet.save(path)
        print(f"written {path}")


if __name__ == "__main__":
    main()
