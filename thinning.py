import numpy as np

def zhang_suen_thinning(binary_image):
    skeleton = binary_image.copy().astype(np.uint8)
    h, w = skeleton.shape
    changed = True
    while changed:
        changed = False
        rows, cols = np.nonzero(skeleton)
        in_bounds = (rows > 0) & (rows < h - 1) & (cols > 0) & (cols < w - 1)
        rows = rows[in_bounds]
        cols = cols[in_bounds]
        to_delete_1 = []
        for r, c in zip(rows, cols):
            p2 = skeleton[r - 1, c]
            p3 = skeleton[r - 1, c + 1]
            p4 = skeleton[r, c + 1]
            p5 = skeleton[r + 1, c + 1]
            p6 = skeleton[r + 1, c]
            p7 = skeleton[r + 1, c - 1]
            p8 = skeleton[r, c - 1]
            p9 = skeleton[r - 1, c - 1]
            b_val = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            if not 2 <= b_val <= 6:
                continue
            transitions = 0
            neighbors = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            for i in range(8):
                if neighbors[i] == 0 and neighbors[i + 1] == 1:
                    transitions += 1
            if transitions != 1:
                continue
            if p2 * p4 * p6 != 0:
                continue
            if p4 * p6 * p8 != 0:
                continue
            to_delete_1.append((r, c))
        if len(to_delete_1) > 0:
            for r, c in to_delete_1:
                skeleton[r, c] = 0
            changed = True
        rows, cols = np.nonzero(skeleton)
        in_bounds = (rows > 0) & (rows < h - 1) & (cols > 0) & (cols < w - 1)
        rows = rows[in_bounds]
        cols = cols[in_bounds]
        to_delete_2 = []
        for r, c in zip(rows, cols):
            p2 = skeleton[r - 1, c]
            p3 = skeleton[r - 1, c + 1]
            p4 = skeleton[r, c + 1]
            p5 = skeleton[r + 1, c + 1]
            p6 = skeleton[r + 1, c]
            p7 = skeleton[r + 1, c - 1]
            p8 = skeleton[r, c - 1]
            p9 = skeleton[r - 1, c - 1]
            b_val = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            if not 2 <= b_val <= 6:
                continue
            transitions = 0
            neighbors = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            for i in range(8):
                if neighbors[i] == 0 and neighbors[i + 1] == 1:
                    transitions += 1
            if transitions != 1:
                continue
            if p2 * p4 * p8 != 0:
                continue
            if p2 * p6 * p8 != 0:
                continue
            to_delete_2.append((r, c))
        if len(to_delete_2) > 0:
            for r, c in to_delete_2:
                skeleton[r, c] = 0
            changed = True
    return skeleton