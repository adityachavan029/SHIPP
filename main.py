import os
import argparse
import numpy as np
import cv2
import math
import preprocessing
import thinning
import minutiae
import encoding
import report

def generate_mock_fingerprint_file(filename='input_images/sample_fingerprint.png'):
    print(f'[*] Generating mock fingerprint image: {filename}...')
    h, w = (300, 300)
    y, x = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
    yc, xc = (150, 150)
    dy = y - yc
    dx = x - xc
    dist = np.sqrt(dx ** 2 + dy ** 2)
    theta = np.arctan2(dy, dx)
    phase = dist / 6.5 - theta
    phase += 0.8 * np.sin(dx / 15.0) * np.cos(dy / 15.0)
    ridges = 127 + 100 * np.sin(phase)
    noise = np.random.normal(0, 15, (h, w))
    img = np.clip(ridges + noise, 0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    r_mask = np.clip(1.0 - (dist / 145.0) ** 4, 0.0, 1.0)
    img = (img * r_mask + 255 * (1.0 - r_mask)).astype(np.uint8)
    cv2.imwrite(filename, img)
    print(f'[+] Mock fingerprint successfully saved as {filename}')

def run_pipeline(image_path):
    print('=' * 80)
    print(f'[Stage 0] Loading Image: {image_path}')
    print('=' * 80)
    os.makedirs('input_images', exist_ok=True)
    os.makedirs('output_images', exist_ok=True)
    if not os.path.exists(image_path):
        if os.path.basename(image_path) == 'sample_fingerprint.png':
            generate_mock_fingerprint_file(image_path)
        else:
            raise FileNotFoundError(f'Specified image file not found: {image_path}')
    print('[Stage 1] Preprocessing...')
    img = preprocessing.load_grayscale_image(image_path)
    img_norm = preprocessing.normalize_image(img)
    img_equal = preprocessing.histogram_equalization(img_norm)
    print('  - Performing local mean binarization (scratch implementation)...')
    binary_img = preprocessing.binarize_local_mean_manual(img_equal, window_size=15, constant=10)
    cv2.imwrite('output_images/step1_binary.png', binary_img * 255)
    print('  [+] Binarized image saved as output_images/step1_binary.png')
    print('[Stage 2] Zhang-Suen Thinning (scratch implementation)...')
    skeleton = thinning.zhang_suen_thinning(binary_img)
    cv2.imwrite('output_images/step2_skeleton.png', skeleton * 255)
    print('  [+] Thinning complete. Skeleton saved as output_images/step2_skeleton.png')
    print('[Stage 3] Detecting Minutiae (Crossing Number method)...')
    all_minutiae = minutiae.compute_crossing_number(skeleton)
    print(f'  - Detected {len(all_minutiae)} raw minutiae candidates.')
    print('[Stage 4] Cleaning Spurious Minutiae...')
    border_mask = minutiae.create_eroded_foreground_mask(binary_img, erode_size=20)
    cv2.imwrite('output_images/step4_mask.png', border_mask * 255)
    print('  [+] Foreground mask generated and saved as output_images/step4_mask.png')
    pruned_minutiae = minutiae.prune_minutiae(all_minutiae, skeleton, border_mask, dist_threshold=10)
    print(f'  - Retained {len(pruned_minutiae)} verified minutiae after spurious removal.')
    print('[Stage 5] Computing Local Ridge Orientations (path tracing)...')
    oriented_minutiae = minutiae.compute_minutiae_orientations(pruned_minutiae, skeleton, window_size=9, max_steps=8)
    print('[Stage 6 & 7] Enoding and Bitstream Consolidation...')
    sorted_minutiae = encoding.sort_minutiae_row_major(oriented_minutiae)
    stats = encoding.generate_final_bitstream(sorted_minutiae)
    print('\n' + '=' * 105)
    print('MINUTIAE EXTRACTION RESULTS TABLE')
    print('=' * 105)
    print(f"| {'No.':<3} | {'x':<5} | {'y':<5} | {'type#':<5} | {'type name':<12} | {'angle(rad)':<10} | {'angle(deg)':<10} | {'binary code':<30} | {'bits':<4} |")
    print('-' * 105)
    for row in stats['table_rows']:
        print(f"| {row['no']:<3} | {row['x']:<5} | {row['y']:<5} | {row['type_num']:<5} | {row['type_name']:<12} | {row['angle_rad']:<10.4f} | {row['angle_deg']:<10} | {row['binary_code']:<30} | {row['bit_count']:<4} |")
    print('=' * 105)
    print('\n' + '=' * 50)
    print('BITSTREAM ANALYSIS')
    print('=' * 50)
    print(f'Total Minutiae Count      : {len(sorted_minutiae)}')
    print(f"Final Bitstream           : {stats['bitstream']}")
    print(f"Total Bitstream Length    : {stats['total_bits']} bits")
    print(f"Number of 0s              : {stats['count_0s']}")
    print(f"Number of 1s              : {stats['count_1s']}")
    print(f"Zero/One Ratio            : {stats['count_0s'] / max(1, stats['count_1s']):.4f}")
    print('=' * 50)
    print('\n[Stage 8] Generating and saving visual overlay...')
    h, w = skeleton.shape
    vis = np.ones((h, w, 3), dtype=np.uint8) * 255
    vis[skeleton == 1] = [64, 64, 64]
    for m in sorted_minutiae:
        x, y = (m['x'], m['y'])
        tid = m['type_id']
        deg = m['angle_deg']
        rad = m['angle_rad']
        color = (0, 0, 255) if tid == 1 else (255, 0, 0)
        cv2.circle(vis, (x, y), 4, color, 1)
        dx = int(12 * np.cos(rad))
        dy = int(12 * np.sin(rad))
        cv2.line(vis, (x, y), (x + dx, y - dy), color, 1)
    cv2.imwrite('output_images/annotated_skeleton.png', vis)
    print('[+] Visual overlay saved as output_images/annotated_skeleton.png (Red: Ending, Blue: Bifurcation)')
    print('=' * 80)
    print('[*] Pipeline completed successfully!')
    print('=' * 80)
    return stats, image_path
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fingerprint Minutiae-to-Bitstream pipeline.')
    parser.add_argument('--image', type=str, default='input_images/sample_fingerprint.png', help='Path to grayscale fingerprint image (default: input_images/sample_fingerprint.png)')
    parser.add_argument('--pdf', action='store_true', default=True, help='Generate PDF report (default: True)')
    parser.add_argument('--no-pdf', dest='pdf', action='store_false', help='Skip PDF generation')
    args = parser.parse_args()
    result = run_pipeline(args.image)
    if args.pdf and result is not None:
        stats, img_path = result
        report.generate_pdf(stats, img_path)