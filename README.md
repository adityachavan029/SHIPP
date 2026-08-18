# SHIPP — Secure Hashed Identity from Fingerprint Processing Pipeline

A research pipeline that converts a raw fingerprint image into a compact binary bitstream and signs it using a post-quantum cryptographic signature scheme (CRYSTALS-Dilithium / ML-DSA-65). The pipeline is implemented entirely from scratch in Python with no reliance on proprietary biometric SDKs.

---

## Pipeline Overview

```
Input Image
    │
    ▼
[Stage 1]  preprocessing.py   — Normalise, equalise, binarise
    │
    ▼
[Stage 2]  thinning.py        — Zhang-Suen skeletonisation
    │
    ▼
[Stage 3]  minutiae.py        — Crossing-number detection, pruning, orientation
    │
    ▼
[Stage 4]  encoding.py        — Binary encoding → final bitstream
    │
    ▼
[Stage 5]  keygen.py          — ML-DSA-65 key-pair generation (liboqs)
    │
    ▼
[Stage 6]  sign.py            — Bitstream → bytes → Dilithium signature
    │
    ▼
[Stage 7]  verify.py          — Signature verification + tamper-detection test
```

Supporting modules: `main.py` (end-to-end orchestration), `report.py` (PDF report), `batch_eval.py` (multi-image statistics).

---

## Stage Details

### Stage 1 — Preprocessing (`preprocessing.py`)

Prepares the raw greyscale fingerprint image for reliable minutiae detection.

| Step | Function | Detail |
|---|---|---|
| Load | `load_grayscale_image()` | Reads image as greyscale via OpenCV. Detects dark-background images by sampling the 10-pixel border; if border mean < 127, inverts the image so ridges are always black on white. |
| Normalise | `normalize_image()` | Linearly stretches pixel values to the full 0–255 range using min-max normalisation. |
| Equalise | `histogram_equalization()` | Applies a scratch CDF-based global histogram equalisation. Skipped automatically when any single pixel value dominates > 50 % of the image (large uniform background guard). |
| Binarise | `binarize_local_mean_manual()` | Adaptive local-mean thresholding with a configurable window (default 15 × 15 px, constant offset = 10). A pixel becomes a ridge (1) when its intensity is more than `constant` below the local mean. Handles uneven illumination that global Otsu cannot. |

An Otsu implementation (`binarize_otsu_manual()`) is also provided for comparison but is not used in the main pipeline.

**Output:** `output_images/step1_binary.png`

---

### Stage 2 — Skeletonisation (`thinning.py`)

Reduces the binary ridge map to a one-pixel-wide skeleton while preserving connectivity and topology.

**Algorithm:** Zhang-Suen iterative thinning (scratch implementation, no OpenCV morphology).

Each iteration applies two sub-passes. In each sub-pass, a foreground pixel is flagged for deletion if all four conditions hold:
1. It has between 2 and 6 foreground neighbours (not an isolated dot or line endpoint).
2. The 8-neighbour sequence contains exactly one 0→1 transition (connectivity preservation).
3. Sub-pass-specific triplet conditions are satisfied (prevent ridge over-erosion).

Deletion is batched per sub-pass so the result is order-independent. Iterates until no pixels change.

**Output:** `output_images/step2_skeleton.png`

---

### Stage 3 — Minutiae Detection & Orientation (`minutiae.py`)

Locates and characterises all fingerprint feature points on the skeleton.

#### 3a — Crossing-Number Detection (`compute_crossing_number`)

For every foreground skeleton pixel, computes the **Crossing Number (CN)**:

```
CN = 0.5 × Σ |P_i − P_{i+1}|   for the 8-neighbourhood cycle
```

| CN value | Minutia type |
|---|---|
| 1 | Ridge Ending |
| 3 | Confirmed Bifurcation |

All other CN values are discarded.

#### 3b — Spurious Minutiae Pruning (`create_eroded_foreground_mask`, `prune_minutiae`)

Two-step filter:
1. **Border mask:** Computes the convex hull of all foreground pixels. Applies a box-filter erosion (default 20 × 20 kernel) to shrink the mask inward, discarding minutiae near noisy image edges.
2. **Distance pruning:** Any two minutiae closer than `dist_threshold = 10 px` are both removed (they are likely caused by skeleton noise, not real features).

#### 3c — Orientation Assignment (`compute_minutiae_orientations`, `trace_ridge_path`)

For each surviving minutia, the local ridge direction is found by tracing up to 8 steps along each skeleton branch:

- **Endings (CN=1):** Single branch → angle = `atan2(dy, dx)` of the traced path.
- **Bifurcations (CN=3):** Three branches → the two most parallel branches are identified by finding the minimum pairwise angular difference; the remaining (most divergent) branch gives the canonical orientation.

Bifurcations where exactly 3 branches cannot be confirmed are discarded, preventing false-positive bifurcation classification.

**Output:** `output_images/step4_mask.png`, `output_images/annotated_skeleton.png` (blue = endings, red = bifurcations).

---

### Stage 4 — Binary Encoding (`encoding.py`)

Converts the oriented minutiae list into a deterministic, fixed-format binary bitstream.

#### Encoding scheme

Each minutia is encoded as a **28-bit word** divided into four fields:

| Field | Bits | Encoding |
|---|---|---|
| x coordinate | 9 | Unsigned integer, clamped to [0, 511] |
| y coordinate | 9 | Unsigned integer, clamped to [0, 511] |
| type_id | 1 | 0 = Ending, 1 = Bifurcation |
| angle_deg | 9 | Integer degrees [0, 359], clamped to [0, 511] |

Fields are concatenated MSB-first: `xxxxxxxxx-yyyyyyyyy-t-aaaaaaaaa`

Minutiae are sorted **row-major** (ascending y, then ascending x) before encoding for a deterministic, image-position-based ordering that is consistent across pipeline runs.

A **safety cap of 50 minutiae** is applied before encoding as a last-resort guard against pathologically noisy images.

`generate_final_bitstream()` returns a dict containing:
- `bitstream` — the full concatenated `'0'`/`'1'` string (e.g. 1036 chars for `3.jpg`)
- `total_bits` — integer length before any padding
- `count_0s`, `count_1s` — bit distribution statistics
- `table_rows` — per-minutia encoding detail for reporting

---

### Stage 5 — Key Generation (`keygen.py`)

Generates and persists a post-quantum signing key pair using **CRYSTALS-Dilithium** (ML-DSA-65), standardised as NIST FIPS 204.

| Property | Value |
|---|---|
| Algorithm | ML-DSA-65 (Dilithium3) |
| NIST security level | 3 (≈ AES-192 classical equivalent) |
| Public key size | 1952 bytes |
| Private key size | 4032 bytes |
| Expected signature size | 3309 bytes |
| Library | `liboqs-python` (open-quantum-safe/liboqs) |

Key generation delegates randomness to the platform CSPRNG via `OQS_SIG_keypair()`. The `oqs.Signature` context manager zeroes native secret-key memory on exit via `OQS_SIG_free()`.

Keys are stored in binary format:

```
keys/dilithium_public.key    — public verification key
keys/dilithium_private.key   — secret signing key  (never committed to VCS)
```

If keys already exist on disk, `generate_and_persist_keys()` loads them rather than regenerating (pass `force=True` to override).

**Usage:**
```bash
python keygen.py
```

---

### Stage 6 — Signing (`sign.py`)

Converts the bitstream to bytes and produces a Dilithium signature.

#### Padding scheme

Bitstream lengths vary per image (e.g. 728, 1036, 1400 bits). To convert to bytes, zero-bits are appended at the **right (least-significant side)**:

```python
padding_bits = (8 - len(bitstring) % 8) % 8
padded       = bitstring + '0' * padding_bits
data         = bytes(int(padded[i:i+8], 2) for i in range(0, len(padded), 8))
```

For `3.jpg` with 1036 bits: `padding_bits = 4`, payload = 130 bytes.

The original bit-length and padding count are stored in a companion `.meta` file so verification can strip the padding exactly.

#### Signing

```python
with oqs.Signature("ML-DSA-65", secret_key=private_key) as signer:
    signature = signer.sign(payload)
```

Dilithium applies internal SHAKE-256 hashing, so variable-length byte inputs are accepted without pre-hashing.

#### Outputs per image

```
signatures/<stem>_signature.bin    — raw signature bytes (3309 B for ML-DSA-65)
signatures/<stem>_signature.meta   — source_image, algorithm, original_bits,
                                     padding_bits, signature_bytes
```

#### Traceability hashes logged

| Hash | Source | Purpose |
|---|---|---|
| `sha256_raw` | SHA-256 of the original unpadded bitstring (ASCII) | Canonical fingerprint identity hash |
| `sha256_payload` | SHA-256 of the padded bytes sent to Dilithium | Lets verifier confirm the exact signed material |

**Usage:**
```bash
python sign.py --image input_images/3.jpg
```

**Example output (`3.jpg`):**
```
Bitstream length          : 1036 bits
Padding appended          : 4 bits  (right zero-padding to nearest byte)
Payload size              : 130 bytes  (1040 bits)
SHA-256 (raw bitstream)   : 4b4f8a6e...
SHA-256 (signed payload)  : 67471d21...
Signing time              : 3.22 ms
Signature size            : 3309 bytes  (26472 bits)
```

---

### Stage 7 — Verification (`verify.py`)

Verifies a stored signature against a freshly re-extracted bitstream, and demonstrates genuine post-quantum tamper detection.

#### Verification flow

1. Re-run the full pipeline (same call chain as `sign.py`) to reconstruct the bitstream.
2. Apply the **identical padding scheme** to reproduce the byte payload.
3. Cross-check `original_bits` and `padding_bits` against the stored `.meta` file — any mismatch means the image changed since signing.
4. Load `keys/dilithium_public.key` and `signatures/<stem>_signature.bin`.
5. Call `oqs.Signature.verify(payload, signature, public_key)` — **Positive case**, expected: `VALID`.

#### Tamper-detection test

A second, genuine `oqs.Signature.verify()` call is made on a **bit-flipped copy** of the payload (one random bit toggled at a deterministic position using `seed=42` for reproducibility):

```python
mask    = 1 << (7 - bit_index)            # MSB-first bit numbering
tampered[byte_index] ^= mask
```

Expected result: `INVALID`. This is not a simulated check — the full Dilithium verifier runs on the corrupted bytes. Suitable for inclusion in a research paper as evidence of tamper detection.

**Usage:**
```bash
python verify.py --image input_images/3.jpg
```

**Example output (`3.jpg`):**
```
  Test                                 Result                    Time
  Positive (original payload)          ✓  VALID               3.32 ms
  Tamper  (1-bit-flipped payload)      ✓  INVALID             0.30 ms

  Overall: ALL CHECKS PASSED ✓
```

---

### Supporting — Report Generation (`report.py`)

Generates a formatted PDF report for a single image using ReportLab.

Sections:
1. **Pipeline image grid** — Original → Binary → Skeleton → Annotated skeleton (2×2 layout with arrows).
2. **Minutiae overview table** — No., x, y, type number, type name, colour, angle (rad + deg).
3. **Binary encoding table** — Per-minutia 28-bit codes with colour-coded field segments.
4. **Final bitstream** — Full concatenated bitstring with per-minutia colour banding.
5. **Statistics** — Total bits, count of 0s and 1s.

**Usage:**
```bash
python main.py --image input_images/3.jpg        # also generates PDF by default
python main.py --image input_images/3.jpg --no-pdf
```

Output: `output_images/fingerprint_report.pdf`

---

### Supporting — Batch Evaluation (`batch_eval.py`)

Runs the full minutiae extraction pipeline (Stages 1–4) over every image in `input_images/` and aggregates statistics.

Per-image metrics: total minutiae, bitstream bits, ending count, bifurcation count.

Summary statistics: mean, median, min, max, standard deviation across all images.

Results are saved to `minutiae_batch_report.csv`.

**Usage:**
```bash
python batch_eval.py
```

---

## File Structure

```
SHIPP/
├── input_images/           — input fingerprint images (.jpg / .png)
├── output_images/          — generated intermediate and report images (gitignored)
├── keys/                   — Dilithium key pair (gitignored — never commit private key)
├── signatures/             — per-image .bin and .meta signature files (gitignored)
├── liboqs/                 — local liboqs build (gitignored)
│
├── preprocessing.py        — Stage 1: image normalisation + binarisation
├── thinning.py             — Stage 2: Zhang-Suen skeletonisation
├── minutiae.py             — Stage 3: CN detection, pruning, orientation
├── encoding.py             — Stage 4: binary encoding + bitstream consolidation
├── keygen.py               — Stage 5: ML-DSA-65 key-pair generation
├── sign.py                 — Stage 6: bitstream signing
├── verify.py               — Stage 7: signature verification + tamper test
│
├── main.py                 — end-to-end orchestration (Stages 1–4 + PDF)
├── report.py               — ReportLab PDF report generator
├── batch_eval.py           — multi-image batch statistics + CSV export
└── requirements.txt        — Python dependencies
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install liboqs-python

# 2. Run full extraction pipeline + PDF report
python main.py --image input_images/3.jpg

# 3. Generate key pair (once)
python keygen.py

# 4. Sign the fingerprint bitstream
python sign.py --image input_images/3.jpg

# 5. Verify the signature + tamper test
python verify.py --image input_images/3.jpg

# 6. Batch evaluate all images in input_images/
python batch_eval.py
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `numpy` | Array operations throughout |
| `opencv-python` | Image I/O, morphological helpers |
| `reportlab` | PDF report generation |
| `liboqs-python` | Python binding for liboqs (Dilithium) |
| `liboqs` (native) | C implementation of ML-DSA-65; auto-downloaded by `liboqs-python` to `%USERPROFILE%\_oqs\build\bin\` on Windows |

---

## Notes

- All core algorithms (normalisation, histogram equalisation, Otsu, local-mean binarisation, Zhang-Suen thinning, crossing-number minutiae detection, CDF-based histogram equalisation) are implemented **from scratch** — no call to `cv2.thinning`, `skimage`, or any biometric SDK.
- The pipeline is **deterministic**: given the same image and the same keys, `sign.py` always produces the same payload bytes (and therefore a verifiable signature), while `verify.py` always reconstructs the identical payload for comparison.