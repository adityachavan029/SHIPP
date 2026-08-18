"""
bitstream_convert.py — Stage 8: Signature-to-Bitstream Conversion (SHIPP Pipeline)
====================================================================================
Converts the raw Dilithium signature bytes (produced by sign.py, Stage 6) into a
clean '0'/'1' bitstring suitable for RTL (Register-Transfer Level) embedding,
simulation, and hardware description language (HDL / Verilog / VHDL) testing.

The output format is intentionally identical to the fingerprint bitstream produced
by encoding.py (Stage 4): a plain ASCII string of '0' and '1' characters, one
character per bit, with no separators or line-breaks inside the bitstream body.
This consistency means downstream RTL tools can handle both bitstreams with the
same parser.

Encoding scheme
---------------
Byte order  : the signature bytes are processed in the order they appear in the
              .bin file (the native output order of oqs.Signature.sign()).
              No byte-order reversal is applied.
Bit order   : within each byte, bits are unpacked **most-significant-bit first**
              (big-endian bit numbering, also called MSB-first).
              Byte value 0xAB = 10101011 is represented as the substring
              '10101011' (bit 7 at the left, bit 0 at the right).
Bit width   : exactly 8 bits per input byte, zero-padded on the left if needed
              (though all bytes are already 8-bit values).
Alphabet    : ASCII characters '0' (0x30) and '1' (0x31) only.

Round-trip guarantee
--------------------
The inverse transform (bitstring → bytes) is:
    data = bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8))
This recovers the original bytes exactly if and only if:
    1. len(bits) % 8 == 0  (guaranteed for a valid signature — no padding needed)
    2. The bit string contains only '0' and '1' characters.
Both conditions are verified and reported.

Inputs / outputs
----------------
Input  : signatures/<stem>_signature.bin   — raw signature bytes (3309 B for ML-DSA-65)
         signatures/<stem>_signature.meta  — metadata used for cross-checks
Output : rtl_bitstreams/<stem>_signature_bits.txt  — ASCII '0'/'1' string (26472 chars
                                                      for a 3309-byte signature)

Usage
-----
    python bitstream_convert.py --image input_images/3.jpg
    python bitstream_convert.py --image input_images/3.jpg --out-dir my_rtl/
"""

import os
import sys
import hashlib
import argparse

# --- Configuration ------------------------------------------------------------

SIGNATURES_DIR  = "signatures"
RTL_DIR_DEFAULT = "rtl_bitstreams"

# --- Core conversion ----------------------------------------------------------

def bytes_to_bitstring(data: bytes) -> str:
    """
    Convert raw bytes to a '0'/'1' bitstring using MSB-first bit ordering.

    Encoding scheme (see module docstring for full specification)
    -------------------------------------------------------------
    - Bytes are processed in their natural file order (no reversal).
    - Within each byte, bit 7 (MSB) is output first, bit 0 (LSB) last.
    - Result is a contiguous ASCII string: no spaces, hyphens, or newlines.
    - Output length is always exactly 8 × len(data) characters.

    Parameters
    ----------
    data : bytes
        Raw input bytes (e.g. Dilithium signature).

    Returns
    -------
    str
        '0'/'1' bitstring of length len(data) * 8.

    Examples
    --------
    >>> bytes_to_bitstring(b'\\xAB')
    '10101011'
    >>> bytes_to_bitstring(b'\\x00\\xFF')
    '0000000011111111'
    """
    return ''.join(format(byte, '08b') for byte in data)


def bitstring_to_bytes(bits: str) -> bytes:
    """
    Convert a '0'/'1' bitstring back to bytes (inverse of bytes_to_bitstring).

    Assumes MSB-first bit ordering and a bit string whose length is a multiple
    of 8.  Processes 8 characters at a time, interpreting each group as one
    big-endian byte.

    Parameters
    ----------
    bits : str
        '0'/'1' string whose length must be divisible by 8.

    Returns
    -------
    bytes
        Reconstructed byte sequence, length = len(bits) // 8.

    Raises
    ------
    ValueError
        If len(bits) % 8 != 0.
    """
    if len(bits) % 8 != 0:
        raise ValueError(
            f"bitstring_to_bytes: bit string length {len(bits)} is not a "
            "multiple of 8.  Cannot reconstruct bytes losslessly."
        )
    return bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8))

# --- File helpers -------------------------------------------------------------

def _sig_path(image_path: str) -> str:
    """Return the expected signature file path for a given image."""
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(SIGNATURES_DIR, f"{stem}_signature.bin")


def _meta_path(image_path: str) -> str:
    """Return the expected .meta file path for a given image."""
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(SIGNATURES_DIR, f"{stem}_signature.meta")


def _rtl_path(image_path: str, out_dir: str) -> str:
    """Return the output RTL bitstream path for a given image."""
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(out_dir, f"{stem}_signature_bits.txt")


def load_signature(image_path: str) -> bytes:
    """
    Load raw signature bytes from signatures/<stem>_signature.bin.

    Raises
    ------
    FileNotFoundError
        If the signature file is missing.  Instruct user to run sign.py first.
    """
    path = _sig_path(image_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Signature file not found: '{path}'\n"
            "  Run Stage 6 first: python sign.py --image <path>"
        )
    with open(path, "rb") as f:
        return f.read()


def load_meta(image_path: str) -> dict:
    """
    Load the .meta file written by sign.py for cross-validation.

    Returns a plain dict; numeric fields (original_bits, padding_bits,
    signature_bytes) are cast to int.
    """
    path = _meta_path(image_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Signature metadata not found: '{path}'\n"
            "  Run Stage 6 first: python sign.py --image <path>"
        )
    meta = {}
    with open(path, "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                meta[k.strip()] = v.strip()
    for field in ("original_bits", "padding_bits", "signature_bytes"):
        if field in meta:
            meta[field] = int(meta[field])
    return meta


def save_bitstream(bitstring: str, image_path: str, out_dir: str) -> str:
    """
    Save the signature bitstring to rtl_bitstreams/<stem>_signature_bits.txt.

    The file contains a single line: the '0'/'1' string followed by a newline.
    No headers, comments, or separators are included so the file can be read
    directly by RTL simulation tools (e.g. $readmemb in Verilog).

    Returns
    -------
    str
        Absolute path of the saved file.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = _rtl_path(image_path, out_dir)
    with open(path, "w") as f:
        f.write(bitstring + "\n")
    return os.path.abspath(path)

# --- Round-trip test ----------------------------------------------------------

def round_trip_test(original_bytes: bytes, bitstring: str) -> tuple[bool, str]:
    """
    Verify that bytes → bitstring → bytes is a lossless round-trip.

    The reconstructed bytes are compared directly against the original using
    an exact byte-for-byte equality check (not just length).  A SHA-256 hash
    of both sides is also computed and reported for traceable verification.

    Parameters
    ----------
    original_bytes : bytes
        The raw signature bytes loaded from disk.
    bitstring : str
        The '0'/'1' string produced by bytes_to_bitstring(original_bytes).

    Returns
    -------
    passed : bool
        True if and only if the reconstructed bytes are byte-for-byte identical
        to original_bytes and the bitstring length is exactly 8 × len(original_bytes).
    detail : str
        Human-readable explanation of the result.
    """
    # Check 1: bit count
    expected_bits = len(original_bytes) * 8
    if len(bitstring) != expected_bits:
        return False, (
            f"Bit count mismatch: expected {expected_bits}, got {len(bitstring)}"
        )

    # Check 2: character set
    invalid = set(bitstring) - {'0', '1'}
    if invalid:
        return False, f"Illegal characters in bitstring: {invalid}"

    # Check 3: exact byte reconstruction
    reconstructed = bitstring_to_bytes(bitstring)
    if reconstructed != original_bytes:
        # Find first differing byte for diagnostics
        for i, (a, b) in enumerate(zip(original_bytes, reconstructed)):
            if a != b:
                return False, (
                    f"Byte mismatch at index {i}: "
                    f"original=0x{a:02X}, reconstructed=0x{b:02X}"
                )
        return False, "Length or content mismatch (no differing byte found — length differs)"

    # Check 4: SHA-256 match
    sha_orig  = hashlib.sha256(original_bytes).hexdigest()
    sha_recon = hashlib.sha256(reconstructed).hexdigest()
    if sha_orig != sha_recon:
        return False, f"SHA-256 mismatch:\n  original     : {sha_orig}\n  reconstructed: {sha_recon}"

    return True, f"Exact byte-for-byte match confirmed  (SHA-256: {sha_orig})"

# --- High-level entry point ---------------------------------------------------

def convert_signature(image_path: str, out_dir: str = RTL_DIR_DEFAULT) -> dict:
    """
    Full Stage 8 flow for one image:
        load signature → convert to bitstring → round-trip test → save

    Parameters
    ----------
    image_path : str
        Path to the source fingerprint image  (used to derive file names).
    out_dir : str
        Output directory for the RTL bitstream text file.

    Returns
    -------
    dict
        Summary of the conversion suitable for display or downstream use.
    """
    # 1. Load raw signature bytes
    print(f"[*] Loading signature for: {image_path}")
    sig_bytes = load_signature(image_path)
    meta      = load_meta(image_path)

    # Cross-check stored signature_bytes against actual file size
    if len(sig_bytes) != meta["signature_bytes"]:
        raise ValueError(
            f"Signature file size ({len(sig_bytes)} B) does not match "
            f".meta record ({meta['signature_bytes']} B).  "
            "Re-sign with: python sign.py --image <path>"
        )

    # 2. Convert bytes → bitstring (MSB-first, big-endian bit ordering)
    print(f"[*] Converting {len(sig_bytes)} bytes → bitstring ...")
    bitstring    = bytes_to_bitstring(sig_bytes)
    total_bits   = len(bitstring)
    sha256_sig   = hashlib.sha256(sig_bytes).hexdigest()

    # 3. Round-trip test: bitstring → bytes → compare
    print(f"[*] Running round-trip integrity test ...")
    rt_passed, rt_detail = round_trip_test(sig_bytes, bitstring)

    # 4. Save
    out_path = save_bitstream(bitstring, image_path, out_dir)
    print(f"[+] RTL bitstream saved → {out_path}")

    return {
        "image_path":    image_path,
        "algorithm":     meta.get("algorithm", "ML-DSA-65"),
        "sig_bytes":     len(sig_bytes),
        "total_bits":    total_bits,
        "sha256_sig":    sha256_sig,
        "rt_passed":     rt_passed,
        "rt_detail":     rt_detail,
        "out_path":      out_path,
        # metadata from sign.py for reference
        "original_bits": meta["original_bits"],
        "padding_bits":  meta["padding_bits"],
    }

# --- __main__ -----------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "SHIPP Stage 8 — Convert Dilithium signature bytes to an RTL-ready "
            "'0'/'1' bitstring."
        )
    )
    parser.add_argument(
        "--image",
        type=str,
        default="input_images/3.jpg",
        help="Path to the source fingerprint image (default: input_images/3.jpg)"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=RTL_DIR_DEFAULT,
        help=f"Output directory for the bitstream file (default: {RTL_DIR_DEFAULT}/)"
    )
    args = parser.parse_args()

    print("=" * 65)
    print("SHIPP Pipeline — Stage 8: Signature Bitstream Conversion")
    print("=" * 65)

    r = convert_signature(args.image, args.out_dir)

    col = 30
    rt_label  = "PASS ✓" if r["rt_passed"] else "FAIL ✗"

    print()
    print("=" * 75)
    print("CONVERSION SUMMARY")
    print("=" * 75)
    print(f"  {'Source image':<{col}}: {r['image_path']}")
    print(f"  {'Algorithm':<{col}}: {r['algorithm']}")
    print(f"  {'Signature size':<{col}}: {r['sig_bytes']} bytes")
    print(f"  {'Bitstream length':<{col}}: {r['total_bits']} bits  "
          f"({r['total_bits'] // 8} bytes × 8)")
    print(f"  {'Encoding':<{col}}: MSB-first, big-endian byte order")
    print(f"  {'SHA-256 (signature bytes)':<{col}}: {r['sha256_sig']}")
    print(f"  {'Round-trip test':<{col}}: {rt_label}")
    print(f"  {'Round-trip detail':<{col}}: {r['rt_detail']}")
    print(f"  {'Output file':<{col}}: {r['out_path']}")
    print()
    print("  ── Fingerprint bitstream reference (from sign.py) ──")
    print(f"  {'Original bitstream bits':<{col}}: {r['original_bits']} bits  "
          f"(fingerprint payload before padding)")
    print(f"  {'Padding at signing':<{col}}: {r['padding_bits']} bits")
    print("=" * 75)

    if not r["rt_passed"]:
        print(f"\n  [!] Round-trip FAILED: {r['rt_detail']}")
        sys.exit(1)
    else:
        print("\n  Round-trip integrity confirmed — no bits lost or corrupted. ✓")
