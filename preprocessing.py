import numpy as np
import cv2

def load_grayscale_image(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f'Grayscale image could not be loaded from path: {image_path}')
    h, w = img.shape
    border_mask = np.ones((h, w), dtype=bool)
    border_mask[10:-10, 10:-10] = False
    border_mean = img[border_mask].mean()
    if border_mean < 127:
        print('[*] Dark background detected. Inverting image to standard format (black ridges on white background)...')
        img = 255 - img
    return img

def normalize_image(img):
    img_min = float(np.min(img))
    img_max = float(np.max(img))
    if img_max - img_min == 0:
        return np.zeros_like(img, dtype=np.uint8)
    normalized = (img.astype(float) - img_min) / (img_max - img_min) * 255.0
    return normalized.astype(np.uint8)

def histogram_equalization(img):
    hist, bins = np.histogram(img.flatten(), bins=256, range=[0, 256])
    max_pixel_pct = np.max(hist) / img.size
    if max_pixel_pct > 0.5:
        print(f'  [~] Large uniform background detected ({max_pixel_pct * 100:.1f}%). Bypassing global histogram equalization.')
        return img
    cdf = hist.cumsum()
    cdf_m = np.ma.masked_equal(cdf, 0)
    cdf_min = cdf_m.min()
    cdf_max = cdf_m.max()
    if cdf_max - cdf_min == 0:
        return np.zeros_like(img, dtype=np.uint8)
    cdf_scaled = (cdf_m - cdf_min) * 255.0 / (cdf_max - cdf_min)
    cdf_equalized = np.ma.filled(cdf_scaled, 0).astype(np.uint8)
    return cdf_equalized[img]

def binarize_otsu_manual(img):
    hist_raw, _ = np.histogram(img.flatten(), bins=256, range=[0, 256])
    total_pixels = float(img.size)
    best_threshold = 0
    max_variance = -1.0
    p_i = hist_raw / total_pixels
    w0_running = np.cumsum(p_i)
    i_p_i_running = np.cumsum(np.arange(256) * p_i)
    mu_T = i_p_i_running[-1]
    for t in range(256):
        w0 = w0_running[t]
        w1 = 1.0 - w0
        if w0 == 0 or w1 == 0:
            continue
        mu0 = i_p_i_running[t] / w0
        mu1 = (mu_T - i_p_i_running[t]) / w1
        variance = w0 * w1 * (mu0 - mu1) ** 2
        if variance > max_variance:
            max_variance = variance
            best_threshold = t
    binary = np.where(img < best_threshold, 1, 0).astype(np.uint8)
    return (binary, best_threshold)

def binarize_local_mean_manual(img, window_size=15, constant=10):
    if window_size % 2 == 0:
        window_size += 1
    local_mean = cv2.blur(img.astype(float), (window_size, window_size))
    binary = np.where(img.astype(float) < local_mean - constant, 1, 0).astype(np.uint8)
    return binary