import os
import csv
import traceback
import statistics

import preprocessing
import thinning
import minutiae as minutiae_mod
import encoding

SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.bmp'}
INPUT_DIR      = 'input_images'
OUTPUT_CSV     = 'minutiae_batch_report.csv'
CSV_FIELDS     = ['filename', 'total_minutiae', 'bitstream_bits', 'ending_count', 'bifurcation_count']


def process_image(image_path):
    img      = preprocessing.load_grayscale_image(image_path)
    img_norm = preprocessing.normalize_image(img)
    img_eq   = preprocessing.histogram_equalization(img_norm)
    binary   = preprocessing.binarize_local_mean_manual(img_eq, window_size=15, constant=10)
    skeleton = thinning.zhang_suen_thinning(binary)

    all_m    = minutiae_mod.compute_crossing_number(skeleton)
    mask     = minutiae_mod.create_eroded_foreground_mask(binary, erode_size=20)
    pruned   = minutiae_mod.prune_minutiae(all_m, skeleton, mask, dist_threshold=10)
    oriented = minutiae_mod.compute_minutiae_orientations(pruned, skeleton)
    sorted_m = encoding.sort_minutiae_row_major(oriented)
    stats    = encoding.generate_final_bitstream(sorted_m)

    rows           = stats['table_rows']
    ending_count   = sum(1 for r in rows if r['type_num'] == 1)
    bifurc_count   = sum(1 for r in rows if r['type_num'] == 3)
    total_minutiae = len(rows)
    bitstream_bits = stats['total_bits']

    return {
        'filename':         os.path.basename(image_path),
        'total_minutiae':   total_minutiae,
        'bitstream_bits':   bitstream_bits,
        'ending_count':     ending_count,
        'bifurcation_count': bifurc_count,
    }


def print_summary_stats(results):
    minutiae_vals = [r['total_minutiae']  for r in results]
    bits_vals     = [r['bitstream_bits']  for r in results]

    def fmt(label, values):
        n = len(values)
        if n == 0:
            print(f"  {label}: no data")
            return
        mean   = statistics.mean(values)
        med    = statistics.median(values)
        mn     = min(values)
        mx     = max(values)
        stdev  = statistics.stdev(values) if n > 1 else 0.0
        print(f"  {label:<20}  mean={mean:.2f}  median={med:.1f}  min={mn}  max={mx}  stdev={stdev:.2f}")

    print()
    print('=' * 70)
    print('SUMMARY STATISTICS')
    print('=' * 70)
    fmt('total_minutiae', minutiae_vals)
    fmt('bitstream_bits', bits_vals)
    print('=' * 70)


def main():
    image_files = sorted(
        f for f in os.listdir(INPUT_DIR)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    )

    if not image_files:
        print(f'[!] No supported images found in "{INPUT_DIR}/".')
        return

    print(f'[*] Found {len(image_files)} image(s) in "{INPUT_DIR}/". Starting batch evaluation...')
    print('=' * 70)

    results = []
    failures = []

    for fname in image_files:
        path = os.path.join(INPUT_DIR, fname)
        print(f'[>] Processing: {fname}')
        try:
            row = process_image(path)
            results.append(row)
            print(f'    minutiae={row["total_minutiae"]}  bits={row["bitstream_bits"]}  '
                  f'endings={row["ending_count"]}  bifurcations={row["bifurcation_count"]}')
        except Exception as exc:
            failures.append((fname, str(exc)))
            print(f'    [!] FAILED — {exc}')
            traceback.print_exc()

    print()
    print('=' * 70)
    print(f'BATCH RESULTS  ({len(results)} succeeded, {len(failures)} failed)')
    print('=' * 70)
    header = f"  {'filename':<20} {'minutiae':>9} {'bits':>6} {'endings':>8} {'bifurcations':>13}"
    print(header)
    print('  ' + '-' * (len(header) - 2))
    for r in results:
        print(f"  {r['filename']:<20} {r['total_minutiae']:>9} {r['bitstream_bits']:>6} "
              f"{r['ending_count']:>8} {r['bifurcation_count']:>13}")

    if failures:
        print()
        print('  Failed images:')
        for fname, err in failures:
            print(f'    - {fname}: {err}')

    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print()
    print(f'[+] CSV report saved → {OUTPUT_CSV}')

    if results:
        print_summary_stats(results)


if __name__ == '__main__':
    main()
