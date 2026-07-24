import cv2
import numpy as np
import math
import preprocessing
import thinning
import minutiae as min_module
import encoding

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

def validate(image_path="input_images/1.jpg"):
    print("=" * 65)
    print(" FINGERPRINT PIPELINE VALIDATION REPORT")
    print("=" * 65)

    # ── Re-run pipeline to get all intermediate data ──────────────────
    img = preprocessing.load_grayscale_image(image_path)
    img_norm  = preprocessing.normalize_image(img)
    img_equal = preprocessing.histogram_equalization(img_norm)
    binary    = preprocessing.binarize_local_mean_manual(img_equal, window_size=15, constant=10)
    skeleton  = thinning.zhang_suen_thinning(binary)
    raw_min   = min_module.compute_crossing_number(skeleton)
    mask      = min_module.create_eroded_foreground_mask(binary, erode_size=20)
    pruned    = min_module.prune_minutiae(raw_min, skeleton, mask, dist_threshold=10)
    oriented  = min_module.compute_minutiae_orientations(pruned, skeleton, window_size=9, max_steps=8)
    sorted_m  = encoding.sort_minutiae_row_major(oriented)
    stats     = encoding.generate_final_bitstream(sorted_m)
    rows      = stats["table_rows"]
    bitstream = stats["bitstream"]

    errors = 0

    # ── TEST 1: Bitstream decode round-trip ───────────────────────────
    print("\n[TEST 1] Bitstream decode round-trip")
    print("-" * 45)
    idx = 0
    for row in rows:
        x_bits     = bin(row["x"])[2:]
        y_bits     = bin(row["y"])[2:]
        type_bits  = bin(row["type_num"])[2:]
        angle_bits = bin(row["angle_deg"])[2:]
        expected   = x_bits + y_bits + type_bits + angle_bits
        actual     = bitstream[idx: idx + row["bit_count"]]
        ok = expected == actual
        if not ok:
            print(f"  {FAIL} Minutia #{row['no']} mismatch — expected {expected}, got {actual}")
            errors += 1
        idx += row["bit_count"]
    remaining = bitstream[idx:]
    if remaining:
        print(f"  {FAIL} Bitstream has {len(remaining)} extra bits after all minutiae")
        errors += 1
    else:
        print(f"  {PASS} All {len(rows)} minutiae decode back correctly. No extra bits.")

    # ── TEST 2: Crossing number re-verification ───────────────────────
    print("\n[TEST 2] Crossing Number re-verification at detected coordinates")
    print("-" * 45)
    h, w = skeleton.shape
    cn_errors = 0
    for row in rows:
        r, c = row["y"], row["x"]
        expected_cn = row["type_num"]  # 1 = ending, 3 = bifurcation
        if skeleton[r, c] != 1:
            print(f"  {FAIL} Minutia #{row['no']} at ({c},{r}) is NOT a skeleton pixel!")
            cn_errors += 1
            continue
        # Re-compute CN manually
        neighbors = [
            skeleton[r-1, c],   # P2 N
            skeleton[r-1, c+1], # P3 NE
            skeleton[r,   c+1], # P4 E
            skeleton[r+1, c+1], # P5 SE
            skeleton[r+1, c],   # P6 S
            skeleton[r+1, c-1], # P7 SW
            skeleton[r,   c-1], # P8 W
            skeleton[r-1, c-1], # P9 NW
        ]
        cn = 0
        for i in range(8):
            cn += abs(int(neighbors[i]) - int(neighbors[(i+1) % 8]))
        cn = cn // 2
        if cn != expected_cn:
            print(f"  {FAIL} Minutia #{row['no']} at ({c},{r}): expected CN={expected_cn}, got CN={cn}")
            cn_errors += 1
    if cn_errors == 0:
        print(f"  {PASS} All {len(rows)} minutiae have correct Crossing Numbers.")
    errors += cn_errors

    # ── TEST 3: Angle range sanity ────────────────────────────────────
    print("\n[TEST 3] Orientation angle range [0°, 359°]")
    print("-" * 45)
    angle_errors = 0
    for row in rows:
        a = row["angle_deg"]
        if not (0 <= a <= 359):
            print(f"  {FAIL} Minutia #{row['no']} has out-of-range angle: {a}°")
            angle_errors += 1
    if angle_errors == 0:
        print(f"  {PASS} All angles within [0°, 359°].")
    errors += angle_errors

    # ── TEST 4: Uniqueness — no duplicate (x, y) ─────────────────────
    print("\n[TEST 4] Uniqueness — no two minutiae at same (x, y)")
    print("-" * 45)
    coords = [(row["x"], row["y"]) for row in rows]
    duplicates = [c for c in set(coords) if coords.count(c) > 1]
    if duplicates:
        print(f"  {FAIL} Duplicate coordinates found: {duplicates}")
        errors += len(duplicates)
    else:
        print(f"  {PASS} All {len(rows)} minutiae have unique coordinates.")

    # ── TEST 5: Bit count consistency ─────────────────────────────────
    print("\n[TEST 5] Bit count consistency (sum of row bits == bitstream length)")
    print("-" * 45)
    sum_bits = sum(row["bit_count"] for row in rows)
    total    = stats["total_bits"]
    if sum_bits != total:
        print(f"  {FAIL} Sum of row bits ({sum_bits}) ≠ bitstream length ({total})")
        errors += 1
    else:
        print(f"  {PASS} Sum of row bits = {sum_bits} = total bitstream length.")

    # ── TEST 6: 0s + 1s == total bits ────────────────────────────────
    print("\n[TEST 6] #0s + #1s == total bits")
    print("-" * 45)
    c0, c1, total = stats["count_0s"], stats["count_1s"], stats["total_bits"]
    if c0 + c1 != total:
        print(f"  {FAIL} {c0} + {c1} = {c0+c1} ≠ {total}")
        errors += 1
    else:
        print(f"  {PASS} {c0} + {c1} = {total}  ✓")

    # ── TEST 7: Border margin check — no minutiae in outer 10px ──────
    print("\n[TEST 7] No minutiae in outer 10-pixel border margin")
    print("-" * 45)
    h, w = skeleton.shape
    border_errors = 0
    for row in rows:
        x, y = row["x"], row["y"]
        if x < 10 or x > w-10 or y < 10 or y > h-10:
            print(f"  {FAIL} Minutia #{row['no']} at ({x},{y}) is in the border margin!")
            border_errors += 1
    if border_errors == 0:
        print(f"  {PASS} No minutiae in border margin.")
    errors += border_errors

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    if errors == 0:
        print(f"\033[92m ALL 7 TESTS PASSED — Data is internally consistent.\033[0m")
    else:
        print(f"\033[91m {errors} ERROR(S) FOUND across 7 tests.\033[0m")
    print("=" * 65)
    print(f"\n{INFO} Minutiae count  : {len(rows)}")
    print(f"{INFO} Total bits      : {stats['total_bits']}")
    print(f"{INFO} 0s / 1s         : {stats['count_0s']} / {stats['count_1s']}")
    print(f"{INFO} Image size      : {w}×{h} px")
    print(f"{INFO} Skeleton pixels : {np.sum(skeleton == 1)}")
    print(f"{INFO} Raw candidates  : {len(raw_min)}")
    print(f"{INFO} After pruning   : {len(pruned)}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--image", default="input_images/1.jpg")
    args = p.parse_args()
    validate(args.image)
