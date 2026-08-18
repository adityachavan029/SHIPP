"""
verify.py — Stage 7: Dilithium Signature Verification (SHIPP Pipeline)
=======================================================================
Verifies the ML-DSA-65 signature produced by sign.py (Stage 4) against the
bitstream re-extracted from the source fingerprint image.

Verification flow
-----------------
1.  Re-run the full image pipeline (same chain as sign.py / main.py):
        preprocessing → thinning → minutiae → encoding.generate_final_bitstream
2.  Apply the IDENTICAL padding scheme used at signing time:
        padding_bits = (8 - len(bitstring) % 8) % 8
        payload      = bitstring + '0' * padding_bits   (padded to byte boundary)
        data         = pack(payload)                     (big-endian, MSB-first)
    The expected padding_bits value is cross-checked against the .meta file so
    any mismatch between the stored signature and the current image is caught.
3.  Load the public key from keys/dilithium_public.key.
4.  Load the signature from signatures/<stem>_signature.bin.
5.  Call oqs.Signature.verify(payload, signature, public_key).

Tamper-detection test (genuine cryptographic check)
----------------------------------------------------
A second oqs.Signature.verify() call is made on a *bit-flipped* copy of the
payload (one random bit toggled).  The expected result is INVALID.  This is
NOT a simulated check — the full Dilithium verifier runs on the corrupted
bytes, demonstrating real post-quantum tamper detection for the paper.

Dependency
----------
liboqs-python 0.16.0+  (pip install liboqs-python)
The native shared library must be on PATH or in the auto-install location:
    Windows: %USERPROFILE%\\_oqs\\build\\bin\\liboqs.dll
    Linux  : set LD_LIBRARY_PATH to the directory containing liboqs.so
Run keygen.py then sign.py before running this script.
"""

import os
import sys
import time
import random
import hashlib
import argparse

# Pipeline modules — same imports as sign.py (single source of truth)
import preprocessing
import thinning
import minutiae as minutiae_mod
import encoding
import keygen

# --- Configuration ------------------------------------------------------------

SIGNATURES_DIR = "signatures"
ALGORITHM      = keygen.ALGORITHM   # "ML-DSA-65" — defined once in keygen.py

# Known auto-install location used by liboqs-python when it downloads liboqs
_OQS_AUTO_DLL_DIR = os.path.join(os.path.expanduser("~"), "_oqs", "build", "bin")

# --- Dependency guard ---------------------------------------------------------

def _import_oqs():
    """
    Import oqs, auto-prepending the liboqs DLL directory on Windows.

    Mirrors sign.py's _import_oqs() exactly so both modules work without
    manual PATH manipulation after a liboqs-python auto-install.
    Auto-install location (Windows): %USERPROFILE%\\_oqs\\build\\bin\\liboqs.dll
    """
    import sys as _sys
    if _sys.platform == "win32" and os.path.isdir(_OQS_AUTO_DLL_DIR):
        os.environ["PATH"] = _OQS_AUTO_DLL_DIR + os.pathsep + os.environ.get("PATH", "")
    try:
        import oqs
        return oqs
    except ImportError:
        raise ImportError(
            "liboqs-python is not installed.\n"
            "  Install with:  pip install liboqs-python\n"
            "  The native shared library (liboqs.dll / liboqs.so) must also be\n"
            "  findable. On Windows: set PATH=C:\\path\\to\\liboqs\\build\\bin;%PATH%\n"
            f"  Auto-install location checked: {_OQS_AUTO_DLL_DIR}"
        )
    except OSError as exc:
        raise OSError(
            "liboqs-python is installed but the native shared library could not be loaded.\n"
            f"  Underlying error: {exc}\n"
            f"  Auto-install location checked: {_OQS_AUTO_DLL_DIR}\n"
            "  On Windows: set PATH=C:\\path\\to\\liboqs\\build\\bin;%PATH%"
        )

# --- Padding (mirrors sign.py bitstring_to_bytes exactly) ---------------------

def bitstring_to_bytes(bitstring: str) -> tuple[bytes, int]:
    """
    Convert a '0'/'1' character string to bytes using right zero-padding.

    Padding scheme (identical to sign.py)
    --------------------------------------
    Zero-bits are appended at the RIGHT (least-significant side):
        padding_bits = (8 - len(bitstring) % 8) % 8
        padded       = bitstring + '0' * padding_bits
    Bytes are packed big-endian (MSB first), 8 chars per byte.

    Returns
    -------
    data : bytes
        Padded bitstring packed into bytes.
    padding_bits : int
        Number of zero-bits appended (0–7).
    """
    padding_bits = (8 - len(bitstring) % 8) % 8
    padded       = bitstring + '0' * padding_bits
    data = bytes(int(padded[i:i+8], 2) for i in range(0, len(padded), 8))
    return data, padding_bits

# --- Pipeline wrapper (mirrors sign.py extract_bitstream exactly) -------------

def extract_bitstream(image_path: str) -> tuple[str, int]:
    """
    Re-run the full SHIPP minutiae extraction pipeline for one image.

    Uses the exact same call chain as sign.py and main.py so the payload
    produced here is byte-identical to what was signed.

    Returns
    -------
    bitstream : str
        '0'/'1' string from encoding.generate_final_bitstream → stats['bitstream'].
    total_bits : int
        Length of the bitstream before padding.

    Raises
    ------
    FileNotFoundError
        If the image does not exist.  Run main.py first (Stage 1–2).
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(
            f"Image not found: '{image_path}'\n"
            "  Run Stage 1 first: python main.py --image <path>"
        )

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

    stats = encoding.generate_final_bitstream(sorted_m)
    return stats['bitstream'], stats['total_bits']

# --- Metadata loader ----------------------------------------------------------

def load_signature_meta(image_path: str) -> dict:
    """
    Load the .meta file written by sign.py alongside the signature.

    The meta file stores:
        source_image, algorithm, original_bits, padding_bits, signature_bytes

    Returns
    -------
    dict with keys: source_image, algorithm, original_bits (int),
                    padding_bits (int), signature_bytes (int)

    Raises
    ------
    FileNotFoundError
        If the .meta file is missing.  Run sign.py first (Stage 4).
    """
    stem      = os.path.splitext(os.path.basename(image_path))[0]
    meta_path = os.path.join(SIGNATURES_DIR, f"{stem}_signature.meta")

    if not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"Signature metadata not found: '{meta_path}'\n"
            "  Run Stage 4 first: python sign.py --image <path>"
        )

    meta = {}
    with open(meta_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()

    # Cast numeric fields
    for int_field in ("original_bits", "padding_bits", "signature_bytes"):
        if int_field in meta:
            meta[int_field] = int(meta[int_field])

    return meta

# --- Signature loader ---------------------------------------------------------

def load_signature(image_path: str) -> bytes:
    """
    Load the raw signature bytes from signatures/<stem>_signature.bin.

    Raises
    ------
    FileNotFoundError
        If the signature file does not exist.  Run sign.py first (Stage 4).
    """
    stem     = os.path.splitext(os.path.basename(image_path))[0]
    sig_path = os.path.join(SIGNATURES_DIR, f"{stem}_signature.bin")

    if not os.path.exists(sig_path):
        raise FileNotFoundError(
            f"Signature file not found: '{sig_path}'\n"
            "  Run Stage 4 first: python sign.py --image <path>"
        )

    with open(sig_path, "rb") as f:
        return f.read()

# --- Verification core --------------------------------------------------------

def verify_payload(payload: bytes, signature: bytes, public_key: bytes) -> tuple[bool, float]:
    """
    Run oqs.Signature.verify() and measure wall-clock time.

    Parameters
    ----------
    payload   : bytes   — the exact padded byte sequence to verify
    signature : bytes   — raw ML-DSA-65 signature bytes
    public_key: bytes   — ML-DSA-65 public key

    Returns
    -------
    is_valid  : bool   — True if signature is cryptographically valid
    elapsed_ms: float  — wall-clock verification time in milliseconds

    Notes
    -----
    oqs.Signature.verify() returns True/False; it never raises on an invalid
    signature (only on malformed inputs).  This is a genuine cryptographic
    check — Dilithium's SHAKE-256-based verification algorithm runs in full.
    """
    oqs = _import_oqs()
    t_start = time.perf_counter()
    with oqs.Signature(ALGORITHM) as verifier:
        is_valid = verifier.verify(payload, signature, public_key)
    elapsed_ms = (time.perf_counter() - t_start) * 1000
    return is_valid, elapsed_ms

# --- Tamper helper ------------------------------------------------------------

def flip_random_bit(data: bytes, seed: int | None = None) -> tuple[bytes, int, int]:
    """
    Return a copy of *data* with exactly one randomly chosen bit flipped.

    Parameters
    ----------
    data : bytes   — original payload
    seed : int | None — RNG seed for reproducibility (None = truly random)

    Returns
    -------
    tampered   : bytes — modified payload
    byte_index : int   — which byte was flipped
    bit_index  : int   — which bit within that byte (0 = MSB)
    """
    rng        = random.Random(seed)
    byte_index = rng.randint(0, len(data) - 1)
    bit_index  = rng.randint(0, 7)
    mask       = 1 << (7 - bit_index)           # MSB-first bit numbering
    flipped    = bytes(
        b ^ mask if i == byte_index else b
        for i, b in enumerate(data)
    )
    return flipped, byte_index, bit_index

# --- High-level entry point ---------------------------------------------------

def verify_image(image_path: str) -> dict:
    """
    Full Stage 7 verification flow for one image.

    Steps
    -----
    1. Re-extract bitstream (same pipeline as sign.py).
    2. Apply identical padding → reconstruct payload bytes.
    3. Cross-check padding_bits against the stored .meta file.
    4. Load public key and signature from disk.
    5. Positive case  — verify(payload, signature, public_key)      → expect VALID.
    6. Tamper case    — flip one random bit, verify tampered payload → expect INVALID.

    Returns a comprehensive result dict for display and downstream use.

    Raises
    ------
    ValueError
        If the reconstructed padding_bits does not match the stored .meta value,
        indicating the image has changed since signing.
    FileNotFoundError
        If the public key, signature, or .meta file is missing.
    """
    # 1. Re-extract bitstream
    print(f"[*] Re-extracting bitstream from: {image_path}")
    bitstream_str, total_bits = extract_bitstream(image_path)

    # 2. Build payload (must be byte-identical to what sign.py signed)
    payload, padding_bits = bitstring_to_bytes(bitstream_str)

    # 3. Cross-check against stored meta
    meta = load_signature_meta(image_path)
    if padding_bits != meta["padding_bits"]:
        raise ValueError(
            f"Padding mismatch — reconstructed {padding_bits} bits but .meta says "
            f"{meta['padding_bits']} bits.  The image may have changed since signing.\n"
            "  Re-sign with: python sign.py --image <path>"
        )
    if total_bits != meta["original_bits"]:
        raise ValueError(
            f"Bitstream length mismatch — extracted {total_bits} bits but .meta says "
            f"{meta['original_bits']} bits.  The image may have changed since signing.\n"
            "  Re-sign with: python sign.py --image <path>"
        )

    sha256_raw     = hashlib.sha256(bitstream_str.encode('ascii')).hexdigest()
    sha256_payload = hashlib.sha256(payload).hexdigest()

    # 4. Load keys and signature
    print(f"[*] Loading public key from: {keygen.PUB_KEY_FILE}")
    try:
        public_key, _ = keygen.load_keys()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Public key not found at '{keygen.PUB_KEY_FILE}'.\n"
            "  Run Stage 3 first: python keygen.py"
        )

    print(f"[*] Loading signature ...")
    signature = load_signature(image_path)

    payload_bytes = len(payload)

    # 5. Positive verification
    print(f"[*] Verifying signature (positive case) ...")
    is_valid, verify_ms = verify_payload(payload, signature, public_key)

    # 6. Tamper test — genuine cryptographic check on bit-flipped payload
    print(f"[*] Running tamper-detection test (flipping one random bit) ...")
    tampered_payload, flip_byte, flip_bit = flip_random_bit(payload, seed=42)
    tampered_sha256       = hashlib.sha256(tampered_payload).hexdigest()
    is_tampered_invalid, tamper_verify_ms = verify_payload(tampered_payload, signature, public_key)
    tamper_detected = not is_tampered_invalid   # True = tamper correctly rejected

    return {
        "image_path":        image_path,
        "total_bits":        total_bits,
        "padding_bits":      padding_bits,
        "payload_bytes":     payload_bytes,
        "sha256_raw":        sha256_raw,
        "sha256_payload":    sha256_payload,
        "sig_bytes":         len(signature),
        # --- Positive case ---
        "is_valid":          is_valid,
        "verify_ms":         verify_ms,
        # --- Tamper case ---
        "flip_byte":         flip_byte,
        "flip_bit":          flip_bit,
        "tampered_sha256":   tampered_sha256,
        "tamper_rejected":   tamper_detected,
        "tamper_verify_ms":  tamper_verify_ms,
    }

# --- __main__ -----------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SHIPP Stage 7 — Verify Dilithium signature of a fingerprint bitstream."
    )
    parser.add_argument(
        "--image",
        type=str,
        default="input_images/3.jpg",
        help="Path to the fingerprint image to verify (default: input_images/3.jpg)"
    )
    args = parser.parse_args()

    print("=" * 65)
    print("SHIPP Pipeline — Stage 7: Dilithium Signature Verification")
    print("=" * 65)

    r = verify_image(args.image)

    col = 28

    # --- Detailed metrics block -----------------------------------------------
    print()
    print("=" * 75)
    print("VERIFICATION DETAILS")
    print("=" * 75)
    print(f"  {'Source image':<{col}}: {r['image_path']}")
    print(f"  {'Algorithm':<{col}}: {ALGORITHM}")
    print(f"  {'Bitstream length':<{col}}: {r['total_bits']} bits")
    print(f"  {'Padding appended at signing':<{col}}: {r['padding_bits']} bits  "
          f"(right zero-padding, matched .meta)")
    print(f"  {'Payload size':<{col}}: {r['payload_bytes']} bytes  "
          f"({r['payload_bytes'] * 8} bits)")
    print(f"  {'Signature size':<{col}}: {r['sig_bytes']} bytes")
    print(f"  {'SHA-256 (raw bitstream)':<{col}}: {r['sha256_raw']}")
    print(f"  {'SHA-256 (verified payload)':<{col}}: {r['sha256_payload']}")
    print(f"  {'SHA-256 (tampered payload)':<{col}}: {r['tampered_sha256']}")
    print(f"  {'Tampered byte / bit':<{col}}: byte[{r['flip_byte']}] bit {r['flip_bit']} (MSB=0)")

    # --- Pass/fail summary table ----------------------------------------------
    print()
    print("=" * 75)
    print("VERIFICATION SUMMARY")
    print("=" * 75)
    pos_label  = "✓  VALID"   if r["is_valid"]        else "✗  INVALID  ← UNEXPECTED"
    tamp_label = "✓  INVALID" if r["tamper_rejected"]  else "✗  VALID    ← UNEXPECTED (tamper undetected!)"

    print(f"  {'Test':<35}  {'Result':<30}  {'Time':>8}")
    print(f"  {'-'*35}  {'-'*30}  {'-'*8}")
    print(f"  {'Positive (original payload)':<35}  {pos_label:<30}  {r['verify_ms']:>6.2f} ms")
    print(f"  {'Tamper  (1-bit-flipped payload)':<35}  {tamp_label:<30}  {r['tamper_verify_ms']:>6.2f} ms")
    print("=" * 75)

    # Exit non-zero if either case gave an unexpected result
    all_pass = r["is_valid"] and r["tamper_rejected"]
    if all_pass:
        print("\n  Overall: ALL CHECKS PASSED ✓")
    else:
        print("\n  Overall: ONE OR MORE CHECKS FAILED ✗")
        sys.exit(1)
