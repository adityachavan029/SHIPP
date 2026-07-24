import numpy as np
import cv2

def compute_crossing_number(skeleton_img):
    h, w = skeleton_img.shape
    minutiae_list = []
    rows, cols = np.nonzero(skeleton_img)
    in_bounds = (rows > 0) & (rows < h - 1) & (cols > 0) & (cols < w - 1)
    rows = rows[in_bounds]
    cols = cols[in_bounds]
    for r, c in zip(rows, cols):
        p2 = int(skeleton_img[r - 1, c])
        p3 = int(skeleton_img[r - 1, c + 1])
        p4 = int(skeleton_img[r, c + 1])
        p5 = int(skeleton_img[r + 1, c + 1])
        p6 = int(skeleton_img[r + 1, c])
        p7 = int(skeleton_img[r + 1, c - 1])
        p8 = int(skeleton_img[r, c - 1])
        p9 = int(skeleton_img[r - 1, c - 1])
        neighbors = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
        cn = 0.5 * sum((abs(neighbors[i] - neighbors[i + 1]) for i in range(8)))
        if cn == 1.0:
            minutiae_list.append((r, c, 1, 'Ending', 1))
        elif cn == 3.0:
            minutiae_list.append((r, c, 3, 'Bifurcation', 3))
    return minutiae_list

def create_eroded_foreground_mask(binary_img, erode_size=15):
    h, w = binary_img.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    coords = np.argwhere(binary_img == 1)
    if len(coords) == 0:
        return mask
    pts = coords[:, [1, 0]]
    hull = cv2.convexHull(pts)
    cv2.drawContours(mask, [hull], -1, 1, thickness=-1)
    ksize = erode_size
    if ksize % 2 == 0:
        ksize += 1
    local_sum = cv2.boxFilter(mask.astype(float), -1, (ksize, ksize), normalize=False)
    eroded_mask = np.where(local_sum >= ksize * ksize - 0.5, 1, 0).astype(np.uint8)
    return eroded_mask

def prune_minutiae(minutiae_list, skeleton_img, border_mask, dist_threshold=10):
    border_filtered = []
    for m in minutiae_list:
        r, c, cn, name, tid = m
        if border_mask[r, c] == 1:
            border_filtered.append(m)
    n = len(border_filtered)
    discard_indices = set()
    dist_threshold_sq = dist_threshold ** 2
    for i in range(n):
        for j in range(i + 1, n):
            r1, c1, _, _, _ = border_filtered[i]
            r2, c2, _, _, _ = border_filtered[j]
            dist_sq = (r1 - r2) ** 2 + (c1 - c2) ** 2
            if dist_sq < dist_threshold_sq:
                discard_indices.add(i)
                discard_indices.add(j)
    pruned_list = [border_filtered[i] for i in range(n) if i not in discard_indices]
    return pruned_list

def trace_ridge_path(skeleton_img, start_point, neighbor_point, max_steps=8):
    h, w = skeleton_img.shape
    path = [start_point, neighbor_point]
    visited = {start_point, neighbor_point}
    curr = neighbor_point
    for _ in range(max_steps - 1):
        r, c = curr
        neighbors_cand = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = (r + dr, c + dc)
                if 0 <= nr < h and 0 <= nc < w:
                    if skeleton_img[nr, nc] == 1 and (nr, nc) not in visited:
                        neighbors_cand.append((nr, nc))
        if len(neighbors_cand) == 0:
            break
        next_pixel = neighbors_cand[0]
        path.append(next_pixel)
        visited.add(next_pixel)
        curr = next_pixel
    return path

def compute_angle_difference(a, b):
    diff = abs(a - b)
    return min(diff, 2 * np.pi - diff)

def compute_minutiae_orientations(minutiae_list, skeleton_img, window_size=9, max_steps=8):
    h, w = skeleton_img.shape
    oriented_minutiae = []
    for m in minutiae_list:
        r, c, cn, name, tid = m
        neighbors_skeleton = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = (r + dr, c + dc)
                if 0 <= nr < h and 0 <= nc < w:
                    if skeleton_img[nr, nc] == 1:
                        neighbors_skeleton.append((nr, nc))
        paths = []
        for neighbor in neighbors_skeleton:
            path = trace_ridge_path(skeleton_img, (r, c), neighbor, max_steps)
            paths.append(path)
        angles = []
        for path in paths:
            if len(path) < 2:
                continue
            start_y, start_x = path[0]
            end_y, end_x = path[-1]
            dx = float(end_x - start_x)
            dy = float(start_y - end_y)
            theta = np.arctan2(dy, dx)
            if theta < 0:
                theta += 2 * np.pi
            angles.append((theta, path))
        final_angle_rad = 0.0
        if tid == 1:
            if len(angles) > 0:
                final_angle_rad = angles[0][0]
        elif tid == 3:
            if len(angles) == 3:
                theta1, theta2, theta3 = (angles[0][0], angles[1][0], angles[2][0])
                diff_12 = compute_angle_difference(theta1, theta2)
                diff_23 = compute_angle_difference(theta2, theta3)
                diff_31 = compute_angle_difference(theta3, theta1)
                min_diff = min(diff_12, diff_23, diff_31)
                if min_diff == diff_12:
                    final_angle_rad = theta3
                elif min_diff == diff_23:
                    final_angle_rad = theta1
                else:
                    final_angle_rad = theta2
            elif len(angles) > 0:
                final_angle_rad = angles[0][0]
        final_angle_deg = int(round(final_angle_rad * 180.0 / np.pi)) % 360
        oriented_minutiae.append({'y': r, 'x': c, 'type_id': tid, 'type_name': name, 'angle_rad': final_angle_rad, 'angle_deg': final_angle_deg})
    return oriented_minutiae