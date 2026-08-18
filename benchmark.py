"""
benchmark.py — End-to-End Pipeline Benchmark (SHIPP Pipeline)
==============================================================
Runs the complete SHIPP pipeline for one or more fingerprint images, times
each stage independently with high-resolution perf_counter timers, and
produces a consolidated results table formatted for direct inclusion in a
research paper.

Stages timed
------------
S1  Minutiae extraction + bitstream generation  (preprocessing → encoding)
S2  Key generation / load (skipped if keys exist; sizes reported either way)
S3  Signing                                     (sign.py)
S4  Verification — positive case                (verify.py)
S5  Verification — tamper case                  (verify.py)
S6  Bitstream conversion                        (bitstream_convert.py)
S7  RTL embedding                               (rtl_embed.py)

All stage functions are called directly from their respective modules —
no subprocess calls, no re-parsing of console output.

Outputs
-------
- Console: aligned results table
- benchmark_results.csv   — one row per image, machine-readable
- benchmark_results.md    — Markdown table, paste directly into paper/README

Usage
-----
    python benchmark.py --image input_images/3.jpg
    python benchmark.py --all
    python benchmark.py --all --rtl rtl/counter.v
"""

import os
import sys
import csv
import time
import argparse
import statistics

# ── Pipeline module imports ────────────────────────────────────────────────────
import preprocessing
import thinning
import minutiae as minutiae_mod
import encoding
import keygen
import sign as sign_mod
import verify as verify_mod
import bitstream_convert as bc_mod
import rtl_embed as rtl_mod

# ── Configuration ──────────────────────────────────────────────────────────────

INPUT_DIR         = "input_images"
SUPPORTED_EXTS    = {".jpg", ".jpeg", ".png", ".bmp"}
RTL_SOURCE_DEFAULT = os.path.join("rtl", "counter.v")
CSV_OUTPUT        = "benchmark_results.csv"
MD_OUTPUT         = "benchmark_results.md"

ALGORITHM         = keygen.ALGORITHM   # "ML-DSA-65"

# ── Stage 1: Minutiae extraction (timed independently) ─────────────────────────

def _run_extraction(image_path: str) -> dict:
    """
    Time Stage 1: full minutiae extraction + bitstream generation.
    Returns the bitstream string, stats, and timing.
    """
    t0 = time.perf_counter()

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

    elapsed_ms = (time.perf_counter() - t0) * 1000

    rows = stats["table_rows"]
    return {
        "bitstream_str":   stats["bitstream"],
        "total_bits":      stats["total_bits"],
        "minutiae_count":  len(rows),
        "ending_count":    sum(1 for r in rows if r["type_num"] == 1),
        "bifurc_count":    sum(1 for r in rows if r["type_num"] == 3),
        "extract_ms":      elapsed_ms,
    }

# ── Stage 2: Key generation (or load) ──────────────────────────────────────────

def _run_keygen() -> dict:
    """
    Time Stage 2: generate keys if missing, otherwise load from disk.
    Always reports key sizes.
    """
    keys_exist = (
        os.path.exists(keygen.PUB_KEY_FILE) and
        os.path.exists(keygen.PRIV_KEY_FILE)
    )
    t0 = time.perf_counter()
    pub, priv = keygen.generate_and_persist_keys(force=False)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {
        "keygen_ms":      elapsed_ms,
        "keys_existed":   keys_exist,
        "pub_key_bytes":  len(pub),
        "priv_key_bytes": len(priv),
    }

# ── Stage 3: Signing (timed at the oqs.sign() level) ───────────────────────────

def _run_signing(image_path: str, bitstream_str: str) -> dict:
    """
    Time Stage 3: pad bitstream → sign → persist.
    Reuses sign_mod.sign_bitstream and sign_mod.save_signature directly.
    """
    _, priv = keygen.load_keys()

    t0 = time.perf_counter()
    signature, padding_bits, sign_ms, sha256_raw, sha256_payload = \
        sign_mod.sign_bitstream(bitstream_str, priv)
    elapsed_total_ms = (time.perf_counter() - t0) * 1000

    total_bits  = len(bitstream_str)
    sig_path    = sign_mod.save_signature(signature, image_path, total_bits, padding_bits)
    payload_bytes = (total_bits + padding_bits) // 8

    return {
        "sign_ms":        sign_ms,           # pure oqs.sign() time
        "sign_total_ms":  elapsed_total_ms,  # includes padding + save
        "padding_bits":   padding_bits,
        "payload_bytes":  payload_bytes,
        "sig_bytes":      len(signature),
        "sha256_raw":     sha256_raw,
        "sha256_payload": sha256_payload,
        "sig_path":       sig_path,
    }

# ── Stages 4 & 5: Verification (positive + tamper) ─────────────────────────────

def _run_verification(image_path: str, bitstream_str: str) -> dict:
    """
    Time Stages 4 & 5: positive verification + tamper-detection test.
    Reconstructs payload from bitstream directly (no redundant re-extraction).
    """
    import hashlib, random

    payload, padding_bits = verify_mod.bitstring_to_bytes(bitstream_str)
    pub, _  = keygen.load_keys()
    sig     = verify_mod.load_signature(image_path)

    # Stage 4 — positive case
    t0 = time.perf_counter()
    is_valid, verify_ms = verify_mod.verify_payload(payload, sig, pub)
    _total_pos_ms = (time.perf_counter() - t0) * 1000

    # Stage 5 — tamper case
    tampered, flip_byte, flip_bit = verify_mod.flip_random_bit(payload, seed=42)
    t0 = time.perf_counter()
    is_tampered_valid, tamper_ms = verify_mod.verify_payload(tampered, sig, pub)
    _total_tamp_ms = (time.perf_counter() - t0) * 1000

    return {
        "verify_ms":       verify_ms,
        "verify_valid":    is_valid,
        "tamper_ms":       tamper_ms,
        "tamper_rejected": not is_tampered_valid,
    }

# ── Stage 6: Bitstream conversion ──────────────────────────────────────────────

def _run_bitstream_convert(image_path: str) -> dict:
    """Time Stage 6: signature bytes → bitstring + round-trip test."""
    sig_bytes = bc_mod.load_signature(image_path)

    t0 = time.perf_counter()
    bitstring = bc_mod.bytes_to_bitstring(sig_bytes)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    rt_passed, _ = bc_mod.round_trip_test(sig_bytes, bitstring)
    out_path = bc_mod.save_bitstream(bitstring, image_path, bc_mod.RTL_DIR_DEFAULT)

    return {
        "convert_ms":   elapsed_ms,
        "sig_bits":     len(bitstring),
        "bc_rt_passed": rt_passed,
        "bc_out_path":  out_path,
    }

# ── Stage 7: RTL embedding ─────────────────────────────────────────────────────

def _run_rtl_embed(image_path: str, rtl_path: str) -> dict:
    """Time Stage 7: load bitstream → embed → extract → round-trip test."""
    bitstring   = rtl_mod.load_bitstream(image_path)
    verilog_src = rtl_mod.load_verilog(rtl_path)

    orig_lines = verilog_src.count("\n")
    orig_bytes = len(verilog_src.encode())

    t_embed = time.perf_counter()
    wm_src  = rtl_mod.embed_watermark(verilog_src, bitstring)
    embed_ms = (time.perf_counter() - t_embed) * 1000

    out_path = rtl_mod.save_watermarked(wm_src, rtl_path)

    t_extract = time.perf_counter()
    with open(out_path, "r") as f:
        saved_src = f.read()
    extracted = rtl_mod.extract_watermark(saved_src)
    extract_ms = (time.perf_counter() - t_extract) * 1000

    rt_passed = (extracted == bitstring)
    wm_lines  = wm_src.count("\n")
    wm_bytes  = len(wm_src.encode())

    return {
        "embed_ms":      embed_ms,
        "extract_ms":    extract_ms,
        "orig_lines":    orig_lines,
        "orig_bytes":    orig_bytes,
        "wm_lines":      wm_lines,
        "wm_bytes":      wm_bytes,
        "rtl_rt_passed": rt_passed,
        "rtl_out_path":  out_path,
    }

# ── Master per-image runner ────────────────────────────────────────────────────

def run_pipeline(image_path: str, rtl_path: str = RTL_SOURCE_DEFAULT) -> dict:
    """
    Run all stages for one image and return a flat result dict.

    Prints a progress indicator per stage but no verbose stage output
    (all print() calls from sub-modules are suppressed via stdout redirect).
    """
    import io, contextlib

    fname = os.path.basename(image_path)
    _silence = contextlib.redirect_stdout(io.StringIO())

    print(f"  [{fname}] S1 extraction ...", end="", flush=True)
    with _silence:
        s1 = _run_extraction(image_path)
    print(f" {s1['extract_ms']:.1f} ms")

    print(f"  [{fname}] S2 keygen/load ...", end="", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        s2 = _run_keygen()
    print(f" {s2['keygen_ms']:.1f} ms {'(loaded)' if s2['keys_existed'] else '(generated)'}")

    print(f"  [{fname}] S3 signing ...", end="", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        s3 = _run_signing(image_path, s1["bitstream_str"])
    print(f" {s3['sign_ms']:.1f} ms")

    print(f"  [{fname}] S4+S5 verification ...", end="", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        s4 = _run_verification(image_path, s1["bitstream_str"])
    print(f" pos={s4['verify_ms']:.1f} ms  tamper={s4['tamper_ms']:.1f} ms")

    print(f"  [{fname}] S6 bitstream convert ...", end="", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        s6 = _run_bitstream_convert(image_path)
    print(f" {s6['convert_ms']:.1f} ms")

    print(f"  [{fname}] S7 RTL embed ...", end="", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        s7 = _run_rtl_embed(image_path, rtl_path)
    print(f" embed={s7['embed_ms']:.1f} ms  extract={s7['extract_ms']:.1f} ms")

    total_ms = (
        s1["extract_ms"] + s2["keygen_ms"] + s3["sign_ms"] +
        s4["verify_ms"]  + s4["tamper_ms"] +
        s6["convert_ms"] + s7["embed_ms"]  + s7["extract_ms"]
    )

    # Assemble flat row
    return {
        "image":            fname,
        # S1
        "minutiae":         s1["minutiae_count"],
        "endings":          s1["ending_count"],
        "bifurcations":     s1["bifurc_count"],
        "bitstream_bits":   s1["total_bits"],
        "extract_ms":       round(s1["extract_ms"], 2),
        # S2
        "pub_key_B":        s2["pub_key_bytes"],
        "priv_key_B":       s2["priv_key_bytes"],
        "keygen_ms":        round(s2["keygen_ms"], 2),
        "keys_existed":     s2["keys_existed"],
        # S3
        "payload_B":        s3["payload_bytes"],
        "sig_B":            s3["sig_bytes"],
        "sign_ms":          round(s3["sign_ms"], 2),
        "padding_bits":     s3["padding_bits"],
        # S4
        "verify_valid":     s4["verify_valid"],
        "verify_ms":        round(s4["verify_ms"], 2),
        # S5
        "tamper_rejected":  s4["tamper_rejected"],
        "tamper_ms":        round(s4["tamper_ms"], 2),
        # S6
        "sig_bits":         s6["sig_bits"],
        "convert_ms":       round(s6["convert_ms"], 2),
        "bc_rt_pass":       s6["bc_rt_passed"],
        # S7
        "orig_rtl_lines":   s7["orig_lines"],
        "wm_rtl_lines":     s7["wm_lines"],
        "embed_ms":         round(s7["embed_ms"], 2),
        "extract_ms_rtl":   round(s7["extract_ms"], 2),
        "rtl_rt_pass":      s7["rtl_rt_passed"],
        # Total
        "total_ms":         round(total_ms, 2),
    }

# ── Formatting helpers ─────────────────────────────────────────────────────────

def _pf(val: bool) -> str:
    return "PASS" if val else "FAIL"

def _console_table(rows: list[dict]) -> None:
    """Print an aligned console table for paper-ready display."""
    W = 90
    print()
    print("=" * W)
    print("SHIPP PIPELINE BENCHMARK RESULTS")
    print("=" * W)

    # Header
    H = (
        f"  {'Image':<14} {'Min':>4} {'Bits':>5} "
        f"{'S1-Ext':>8} {'S3-Sign':>8} {'S4-Ver':>7} {'S5-Tamp':>8} "
        f"{'S6-Conv':>8} {'S7-Emb':>7} {'Total':>8}  "
        f"{'Ver':>5} {'Tamp':>5} {'BC-RT':>5} {'WM-RT':>5}"
    )
    print(H)
    print("  " + "-" * (W - 2))

    for r in rows:
        print(
            f"  {r['image']:<14} "
            f"{r['minutiae']:>4} "
            f"{r['bitstream_bits']:>5} "
            f"{r['extract_ms']:>7.1f}ms "
            f"{r['sign_ms']:>7.1f}ms "
            f"{r['verify_ms']:>6.1f}ms "
            f"{r['tamper_ms']:>7.1f}ms "
            f"{r['convert_ms']:>7.1f}ms "
            f"{r['embed_ms']:>6.1f}ms "
            f"{r['total_ms']:>7.1f}ms  "
            f"{'OK':>5} "
            f"{'OK' if r['tamper_rejected'] else 'FAIL':>5} "
            f"{_pf(r['bc_rt_pass']):>5} "
            f"{_pf(r['rtl_rt_pass']):>5}"
        )

    if len(rows) > 1:
        _summary_row(rows, W)

    print("=" * W)
    print()
    print("  Columns: Min=minutiae  Bits=bitstream length  S1..S7=stage times (ms)")
    print("  Ver=signature valid  Tamp=tamper rejected  BC-RT/WM-RT=round-trip tests")


def _summary_row(rows: list[dict], W: int) -> None:
    nums = lambda key: [r[key] for r in rows]
    _agg = {"mean": statistics.mean, "min": min, "max": max}
    print("  " + "-" * (W - 2))
    for label in ("mean", "min", "max"):
        agg   = _agg[label]
        ext   = agg(nums("extract_ms"))
        sign  = agg(nums("sign_ms"))
        ver   = agg(nums("verify_ms"))
        tamp  = agg(nums("tamper_ms"))
        conv  = agg(nums("convert_ms"))
        emb   = agg(nums("embed_ms"))
        tot   = agg(nums("total_ms"))
        bits  = agg(nums("bitstream_bits"))
        minu  = agg(nums("minutiae"))
        print(
            f"  {label.upper():<14} "
            f"{minu:>4.0f} "
            f"{bits:>5.0f} "
            f"{ext:>7.1f}ms "
            f"{sign:>7.1f}ms "
            f"{ver:>6.1f}ms "
            f"{tamp:>7.1f}ms "
            f"{conv:>7.1f}ms "
            f"{emb:>6.1f}ms "
            f"{tot:>7.1f}ms"
        )


def _write_csv(rows: list[dict]) -> None:
    fields = list(rows[0].keys())
    with open(CSV_OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [+] CSV saved  → {CSV_OUTPUT}")


def _write_markdown(rows: list[dict]) -> None:
    cols = [
        ("Image",       "image",          "<"),
        ("Minutiae",    "minutiae",        ">"),
        ("Bits",        "bitstream_bits",  ">"),
        ("S1 ext (ms)", "extract_ms",      ">"),
        ("S3 sign (ms)","sign_ms",         ">"),
        ("S4 ver (ms)", "verify_ms",       ">"),
        ("S5 tamp (ms)","tamper_ms",       ">"),
        ("S6 conv (ms)","convert_ms",      ">"),
        ("S7 emb (ms)", "embed_ms",        ">"),
        ("Total (ms)",  "total_ms",        ">"),
        ("Verify",      "verify_valid",    "^"),
        ("Tamper",      "tamper_rejected", "^"),
        ("BC RT",       "bc_rt_pass",      "^"),
        ("WM RT",       "rtl_rt_pass",     "^"),
    ]
    headers = [c[0] for c in cols]
    keys    = [c[1] for c in cols]

    def fmt(val):
        if isinstance(val, bool):
            return "✓" if val else "✗"
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(
        ":---:" if a == "^" else ("---:" if a == ">" else ":---")
        for _, _, a in cols
    ) + " |")
    for r in rows:
        lines.append("| " + " | ".join(fmt(r[k]) for k in keys) + " |")

    # Summary row for multi-image
    if len(rows) > 1:
        num_cols = [k for k in keys if isinstance(rows[0][k], (int, float))]
        mean_row = {"image": "**Mean**"}
        for k in keys[1:]:
            vals = [r[k] for r in rows]
            if isinstance(vals[0], (int, float)):
                mean_row[k] = round(statistics.mean(vals), 2)
            else:
                mean_row[k] = ""
        lines.append("| " + " | ".join(fmt(mean_row.get(k, "")) for k in keys) + " |")

    header_md = (
        "## SHIPP Pipeline Benchmark Results\n\n"
        f"Algorithm: **{ALGORITHM}**  \n"
        "Times in milliseconds (ms). All stages measured with `time.perf_counter()`.\n\n"
    )
    with open(MD_OUTPUT, "w", encoding="utf-8") as f:
        f.write(header_md + "\n".join(lines) + "\n")
    print(f"  [+] Markdown saved → {MD_OUTPUT}")

# ── __main__ ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SHIPP end-to-end pipeline benchmark — times all 7 stages."
    )
    parser.add_argument(
        "--image",
        type=str,
        default="input_images/3.jpg",
        help="Path to the fingerprint image (default: input_images/3.jpg)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Benchmark every image in input_images/ and produce multi-row output"
    )
    parser.add_argument(
        "--rtl",
        type=str,
        default=RTL_SOURCE_DEFAULT,
        help=f"Host Verilog module for Stage 7 (default: {RTL_SOURCE_DEFAULT})"
    )
    args = parser.parse_args()

    print("=" * 65)
    print("SHIPP Pipeline — End-to-End Benchmark")
    print("=" * 65)

    if args.all:
        image_files = sorted(
            os.path.join(INPUT_DIR, f)
            for f in os.listdir(INPUT_DIR)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
        )
        if not image_files:
            print(f"[!] No supported images found in '{INPUT_DIR}/'.")
            sys.exit(1)
        print(f"[*] Benchmarking {len(image_files)} images ...\n")
    else:
        image_files = [args.image]
        print(f"[*] Benchmarking: {args.image}\n")

    results = []
    failures = []

    for img_path in image_files:
        print(f"[>] {os.path.basename(img_path)}")
        try:
            row = run_pipeline(img_path, args.rtl)
            results.append(row)
        except Exception as exc:
            failures.append((img_path, str(exc)))
            print(f"    [!] FAILED — {exc}")

    if not results:
        print("[!] No results to display.")
        sys.exit(1)

    # Print console table
    _console_table(results)

    # Save outputs
    print()
    _write_csv(results)
    _write_markdown(results)

    if failures:
        print()
        print(f"  [!] {len(failures)} image(s) failed:")
        for path, err in failures:
            print(f"      {path}: {err}")
