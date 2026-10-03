"""Measurements behind the step-2 decisions (cloud mask and polygon shrink) on one parcel.

1. Edge profile: median NDVI by distance from the parcel outline, on the clear dates. Shows how
   many metres it takes to go from the neighbour's value to the field's value, i.e. how far the
   border contaminates pixels. Inside distances are positive, outside negative.
2. Cloud mask on the cloudy date: share of the parcel left valid for two ways of choosing SCL
   classes and several widenings of the mask.
3. Haze around clouds: for pixels that the mask keeps on the cloudy date, how much lower their
   NDVI is than on the last clear date, grouped by distance to the nearest masked pixel. If pixels
   next to a cloud are darker than those far from it, the cloud reaches further than SCL says.

    python measure_mask.py demo1 --cloudy 2026-07-28 --clear 2026-07-18
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_dilation, distance_transform_edt

from common import OUT, colorize_ndvi, load_parcels, ndvi, polygon_mask, polygon_pixels, read_asset, reflectance, \
    study_scenes, to_10m

# A: throw away only what is known to be bad. B: keep only what is known to be good.
DENY = [0, 1, 3, 8, 9, 10, 11]  # no data, saturated, shadow, cloud medium/high, cirrus, snow
ALLOW = [4, 5, 6]               # vegetation, bare soil, water
WIDEN_M = [0, 20, 40, 60, 100]
HAZE_BINS_M = [10, 20, 30, 40, 60, 80, 100, 150]


def disk(radius_px):
    y, x = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    return x * x + y * y <= radius_px * radius_px


def load(parcel_id, scene):
    red = reflectance(read_asset(parcel_id, scene, "red")[0][0], scene)
    nir = reflectance(read_asset(parcel_id, scene, "nir")[0][0], scene)
    scl20, _, _ = read_asset(parcel_id, scene, "scl")
    visual, transform, crs = read_asset(parcel_id, scene, "visual")
    return {"ndvi": ndvi(red, nir), "scl20": scl20[0], "rgb": np.moveaxis(visual, 0, -1),
            "transform": transform, "crs": crs}


def invalid_mask(scl20, rule, widen_m):
    """Unusable pixels on the 10 m grid. Widening is done on the 20 m SCL grid, in whole 20 m pixels."""
    bad = np.isin(scl20, DENY) if rule == "A" else ~np.isin(scl20, ALLOW)
    if widen_m:
        bad = binary_dilation(bad, structure=disk(widen_m // 20))
    return to_10m(bad)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parcel")
    ap.add_argument("--cloudy", required=True)
    ap.add_argument("--clear", required=True)
    args = ap.parse_args()

    parcel = load_parcels()[args.parcel]
    scenes = {s["date"]: s for s in study_scenes(args.parcel)}
    data = {d: load(args.parcel, s) for d, s in scenes.items()}
    any_d = data[args.clear]
    mask = polygon_mask(parcel["geometry"], any_d["transform"], any_d["crs"], any_d["ndvi"].shape)
    n = mask.sum()

    # 1. Edge profile, in whole 10 m pixels from the outline (pixel centres).
    inside_d = distance_transform_edt(mask)
    outside_d = distance_transform_edt(~mask)
    signed = np.where(mask, np.ceil(inside_d - 0.5), -np.ceil(outside_d - 0.5)).astype(int)
    clear_dates = [d for d in data if d != args.cloudy]
    print("1. Edge profile: median NDVI by distance from the outline (+ inside, - outside)")
    print("   distance  " + "  ".join(f"{d:>10s}" for d in clear_dates) + "   pixels")
    for k in range(-6, 9):
        sel = signed == k
        if sel.sum() == 0:
            continue
        label = f"{k * 10:+d} m" if k < 8 else "+80 m+"
        sel = signed >= 8 if k == 8 else sel
        print(f"   {label:>8s}  " + "  ".join(f"{np.nanmedian(data[d]['ndvi'][sel]):10.3f}" for d in clear_dates)
              + f"   {sel.sum():6d}")

    # 2. Valid share on the cloudy date.
    cloudy = data[args.cloudy]
    print(f"\n2. {args.cloudy}: share of the {n} parcel pixels left valid")
    print("   widen by   " + "  ".join(f"{w:>5d} m" for w in WIDEN_M))
    for rule, label in [("A", "A deny-list"), ("B", "B allow-list")]:
        vals = [100 * (~invalid_mask(cloudy["scl20"], rule, w))[mask].mean() for w in WIDEN_M]
        print(f"   {label:12s}" + "  ".join(f"{v:6.1f}%" for v in vals))

    # 3. Haze: NDVI drop vs the clear date, by distance to the nearest masked pixel (rule B, no widening).
    bad = invalid_mask(cloudy["scl20"], "B", 0)
    dist_m = 10 * distance_transform_edt(~bad)
    kept = mask & ~bad
    diff = cloudy["ndvi"] - data[args.clear]["ndvi"]
    print(f"\n3. Kept pixels (rule B, no widening): NDVI {args.cloudy} minus {args.clear}, by distance to the mask")
    lo = 0
    for hi in HAZE_BINS_M + [10_000]:
        sel = kept & (dist_m > lo) & (dist_m <= hi)
        if sel.any():
            label = f"{lo}-{hi} m" if hi < 10_000 else f">{lo} m"
            print(f"   {label:>10s}: median {np.median(diff[sel]):+.3f}   pixels {sel.sum():5d}")
        lo = hi

    # Picture: RGB, the two rules without widening, rule B widened by 40 m, NDVI with that mask.
    ring = polygon_pixels(parcel["geometry"], any_d["transform"], any_d["crs"])
    scale = 4
    font = ImageFont.load_default(size=18)
    panels = []
    for title, arr in [
        (f"{args.cloudy} RGB", cloudy["rgb"]),
        ("A deny-list, 0 m", np.where(invalid_mask(cloudy["scl20"], "A", 0)[..., None], 255, cloudy["rgb"] // 2)),
        ("B allow-list, 0 m", np.where(invalid_mask(cloudy["scl20"], "B", 0)[..., None], 255, cloudy["rgb"] // 2)),
        ("B allow-list, 40 m", np.where(invalid_mask(cloudy["scl20"], "B", 40)[..., None], 255, cloudy["rgb"] // 2)),
        ("NDVI, B 40 m", colorize_ndvi(cloudy["ndvi"], invalid_mask(cloudy["scl20"], "B", 40))),
    ]:
        img = Image.fromarray(arr.astype(np.uint8)).resize((arr.shape[1] * scale, arr.shape[0] * scale), Image.NEAREST)
        draw = ImageDraw.Draw(img)
        draw.line([(x * scale, y * scale) for x, y in ring], fill=(255, 0, 255), width=2)
        draw.text((6, 4), title, font=font, fill="white", stroke_width=3, stroke_fill="black")
        panels.append(img)
    w, h = panels[0].size
    out = Image.new("RGB", (len(panels) * (w + 6), h), "white")
    for i, p in enumerate(panels):
        out.paste(p, (i * (w + 6), 0))
    path = OUT / args.parcel / "mask_study.png"
    out.save(path)
    print(f"\nwritten {path}  (white = thrown away; the rest is the RGB, darkened)")


if __name__ == "__main__":
    main()
