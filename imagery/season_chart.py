"""Season chart per parcel, from out/imagery.json only (what the server and frontend get).

Top panel: ndvi_median and ndmi_median (same index scale, one axis). Bottom panel: affected_pct.
A strip between them marks the scenes skipped for clouds. Labels are in Romanian: the chart is for
the team and the jury.

    python season_chart.py      ->  out/<parcel>/season.png
"""
import json
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont

from analyze import MAX_GAP_DAYS, OUTPUT
from common import OUT, load_parcels

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
NDVI_COLOR, NDMI_COLOR = "#2a78d6", "#eb6834"  # categorical slots 1 and 2 of the reference palette
MONTHS = {1: "ian", 2: "feb", 3: "mar", 4: "apr", 5: "mai", 6: "iun", 7: "iul", 8: "aug", 9: "sep", 10: "oct",
          11: "noi", 12: "dec"}
CROPS = {"wheat": "grâu", "corn": "porumb", "sunflower": "floarea-soarelui", "orchard": "livadă",
         "vineyard": "viță-de-vie"}
W, LEFT, RIGHT = 1400, 90, 90
TOP_Y0, TOP_Y1 = 110, 470        # index panel
STRIP_Y = 510                    # skipped scenes
BOT_Y0, BOT_Y1 = 560, 760        # affected panel
H = 820


FONTS = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]  # need Romanian letters (ă, ș, ț)


def font(size):
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def num(v, decimals):
    """Romanian number format: decimal comma."""
    return f"{v:.{decimals}f}".replace(".", ",")


def day_text(d):
    return f"{d.day} {MONTHS[d.month]} {d.year}"


def segments(results, key, x, y):
    """Chart points, split where two scenes are more than MAX_GAP_DAYS apart: no line across a gap."""
    out, prev = [], None
    for r in results:
        day = date.fromisoformat(r["scene_date"])
        if prev is None or (day - prev).days > MAX_GAP_DAYS:
            out.append([])
        out[-1].append((x(day), y(r[key])))
        prev = day
    return out


def chart(parcel_id, parcel, results, skipped):
    days = [date.fromisoformat(r["scene_date"]) for r in results] + [date.fromisoformat(s["scene_date"]) for s in skipped]
    start, end = date(min(days).year, min(days).month, 1), max(days) + timedelta(days=3)
    x = lambda d: LEFT + (d - start).days / (end - start).days * (W - LEFT - RIGHT)
    y_idx = lambda v: TOP_Y1 - (v + 0.5) / 1.5 * (TOP_Y1 - TOP_Y0)          # index axis -0.5 .. 1.0
    top_aff = max(5.0, max(r["affected_pct"] for r in results) * 1.2)
    y_aff = lambda v: BOT_Y1 - v / top_aff * (BOT_Y1 - BOT_Y0)

    img = Image.new("RGB", (W, H), SURFACE)
    d = ImageDraw.Draw(img)
    props = parcel["properties"] if parcel else {}
    crop = CROPS.get(props.get("crop"), props.get("crop") or "?")
    d.text((LEFT, 24), f"{props.get('name', parcel_id)} ({parcel_id}): {day_text(min(days))} – {day_text(max(days))}",
           font=font(26), fill=INK)
    d.text((LEFT, 58), f"Cultură {'confirmată' if props.get('crop_confirmed') else 'presupusă'}: {crop}. "
           "Mediana NDVI (verdeață) și NDMI (apa din frunze), din scenele Sentinel-2 acceptate.",
           font=font(16), fill=INK2)

    # Index panel: recessive grid, a baseline at 0, one axis.
    for v in [-0.5, 0.0, 0.5, 1.0]:
        d.line([(LEFT, y_idx(v)), (W - RIGHT, y_idx(v))], fill=BASELINE if v == 0 else GRID, width=1)
        d.text((LEFT - 10, y_idx(v)), num(v, 1), font=font(14), fill=MUTED, anchor="rm")
    for key, color, label in [("ndvi_median", NDVI_COLOR, "NDVI"), ("ndmi_median", NDMI_COLOR, "NDMI")]:
        parts = segments(results, key, x, y_idx)
        for part in parts:
            d.line(part, fill=color, width=2)
        pts = [p for part in parts for p in part]
        for px, py in pts:  # 8 px markers with a 2 px surface ring
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=SURFACE)
            d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=color)
        d.text((pts[-1][0] + 12, pts[-1][1]), label, font=font(16), fill=INK, anchor="lm")
    peak = max(results, key=lambda r: r["ndvi_median"])
    px, py = x(date.fromisoformat(peak["scene_date"])), y_idx(peak["ndvi_median"])
    d.text((px, py - 14), num(peak["ndvi_median"], 2), font=font(14), fill=INK2, anchor="mb")

    # Skipped scenes strip.
    d.text((LEFT - 10, STRIP_Y), "sărite", font=font(14), fill=MUTED, anchor="rm")
    for s in skipped:
        sx = x(date.fromisoformat(s["scene_date"]))
        d.line([(sx, STRIP_Y - 8), (sx, STRIP_Y + 8)], fill=MUTED, width=2)

    # Affected panel.
    d.text((LEFT, BOT_Y0 - 28), "Vegetație slabă (% din parcela vizibilă)", font=font(16), fill=INK2)
    for v in [0, top_aff / 2, top_aff]:
        d.line([(LEFT, y_aff(v)), (W - RIGHT, y_aff(v))], fill=BASELINE if v == 0 else GRID, width=1)
        d.text((LEFT - 10, y_aff(v)), num(v, 0 if v == int(v) else 1) + "%", font=font(14), fill=MUTED, anchor="rm")
    for r in results:
        bx = x(date.fromisoformat(r["scene_date"]))
        if r["affected_pct"] > 0:
            d.rounded_rectangle([bx - 6, y_aff(r["affected_pct"]), bx + 6, y_aff(0)], radius=4, fill=NDVI_COLOR)
    worst = max(results, key=lambda r: r["affected_pct"])
    wx = x(date.fromisoformat(worst["scene_date"]))
    d.text((wx, y_aff(worst["affected_pct"]) - 6), num(worst["affected_pct"], 1) + "%", font=font(14), fill=INK2,
           anchor="mb")

    # Shared date axis: 1st and 15th of every month.
    t = start
    while t <= end:
        if t.day in (1, 15):
            tx = x(t)
            d.line([(tx, BOT_Y1), (tx, BOT_Y1 + 5)], fill=BASELINE)
            d.text((tx, BOT_Y1 + 8), f"{t.day} {MONTHS.get(t.month, t.month)}", font=font(14), fill=MUTED, anchor="mt")
        t += timedelta(days=1)

    # Legend row (two series: legend plus direct labels).
    lx = W - RIGHT - 420
    for i, (color, label) in enumerate([(NDVI_COLOR, "NDVI median"), (NDMI_COLOR, "NDMI median"),
                                        (MUTED, "scenă sărită (nori)")]):
        cx = lx + i * 145
        d.ellipse([cx, 83, cx + 10, 93], fill=color)
        d.text((cx + 16, 88), label, font=font(14), fill=INK2, anchor="lm")

    path = OUT / parcel_id / "season.png"
    img.save(path)
    return path


def main():
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    parcels = load_parcels()
    for pid in sorted({r["parcel_id"] for r in data["results"]}):
        results = sorted((r for r in data["results"] if r["parcel_id"] == pid), key=lambda r: r["scene_date"])
        skipped = [s for s in data["skipped"] if s["parcel_id"] == pid]
        print(f"written {chart(pid, parcels.get(pid), results, skipped)}")


if __name__ == "__main__":
    main()
