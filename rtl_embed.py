"""
rtl_embed.py — Stage 9: Signature Bitstream RTL Embedding (SHIPP Pipeline)
===========================================================================
Embeds the Dilithium signature bitstream (produced by bitstream_convert.py,
Stage 8) into a Verilog RTL module as a watermark, then extracts it back and
confirms an exact bit-for-bit round-trip match.

PROOF-OF-CONCEPT DISCLAIMER
----------------------------
This module demonstrates the *feasibility* of embedding a post-quantum
signature bitstream into RTL source code.  It is NOT a synthesis-validated
production embedding.  Specifically:

  - The embedded localparam block is technically synthesisable Verilog, but
    synthesis optimisation (constant folding, dead-code elimination) may strip
    unused constants depending on tool settings.  Preserving watermarks through
    synthesis is a separate research problem (synthesis-resistant watermarking)
    and is outside the scope of this proof-of-concept.
  - In a real IP core the 26 472-bit watermark would occupy a proportionally
    small fraction of the design (a 100 k-gate core has ~1.6 M bits of state).
    Here it dominates the toy counter deliberately, to test the embedding
    mechanism in isolation.
  - Synthesis validation and area-impact analysis are identified as future work.

Embedding approach — localparam block with tagged region markers
----------------------------------------------------------------
The bitstream is stored as a series of Verilog localparam string constants,
each holding 64 bits (one line) of the bitstream.  A pair of sentinel comment
lines delimit the watermark region:

    // SHIPP_WATERMARK_BEGIN bits=<N>
    localparam [63:0] _wm_0000 = 64'b<64 bits>;
    localparam [63:0] _wm_0001 = 64'b<64 bits>;
    ...
    // SHIPP_WATERMARK_END

Tradeoffs vs alternatives
--------------------------
| Approach                  | Pros                         | Cons                          |
|---------------------------|------------------------------|-------------------------------|
| localparam string         | Standard Verilog; readable;  | Unused consts may be stripped |
| (chosen)                  | easy extraction; chunk size  | by aggressive synthesis opts  |
|                           | tunable                      |                               |
|---------------------------|------------------------------|-------------------------------|
| Unused register block     | Harder to strip              | Requires clock/reset logic;   |
|                           |                              | non-trivial to extract        |
|---------------------------|------------------------------|-------------------------------|
| Structured comment        | Synthesis-transparent (never | Comments stripped by some     |
|                           | synthesised)                 | netlist flows; not in netlist |

Inputs / outputs
----------------
Input  : rtl/<module>.v                    — host RTL module (e.g. rtl/counter.v)
         rtl_bitstreams/<stem>_signature_bits.txt — bitstring from Stage 8
Output : outputs/<module>_watermarked.v   — watermarked Verilog file

Usage
-----
    python rtl_embed.py --image input_images/3.jpg
    python rtl_embed.py --image input_images/3.jpg --rtl rtl/counter.v
"""

import os
import sys
import re
import hashlib
import argparse

# --- Configuration ------------------------------------------------------------

RTL_BITSTREAMS_DIR    = "rtl_bitstreams"
RTL_SOURCE_DEFAULT    = os.path.join("rtl", "counter.v")
OUTPUTS_DIR           = "outputs"

WATERMARK_BEGIN_TAG   = "SHIPP_WATERMARK_BEGIN"
WATERMARK_END_TAG     = "SHIPP_WATERMARK_END"
BITS_PER_LINE         = 64          # localparam width in bits (one line per chunk)
PARAM_PREFIX          = "_wm_"      # prefix for watermark localparam names

# --- Bitstream loader ---------------------------------------------------------

def _rtl_bits_path(image_path: str) -> str:
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(RTL_BITSTREAMS_DIR, f"{stem}_signature_bits.txt")


def load_bitstream(image_path: str) -> str:
    """
    Load the signature bitstring from rtl_bitstreams/<stem>_signature_bits.txt.

    Raises
    ------
    FileNotFoundError
        If the bitstream file is missing.  Run Stage 8 first.
    """
    path = _rtl_bits_path(image_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"RTL bitstream file not found: '{path}'\n"
            "  Run Stage 8 first: python bitstream_convert.py --image <path>"
        )
    with open(path, "r") as f:
        bits = f.read().strip()
    # Validate character set
    invalid = set(bits) - {'0', '1'}
    if invalid:
        raise ValueError(f"Unexpected characters in bitstream file: {invalid}")
    return bits


def load_verilog(rtl_path: str) -> str:
    """Load the host Verilog module source as a string."""
    if not os.path.exists(rtl_path):
        raise FileNotFoundError(
            f"RTL source not found: '{rtl_path}'\n"
            "  Expected rtl/counter.v — check the repo or supply --rtl <path>"
        )
    with open(rtl_path, "r") as f:
        return f.read()

# --- Watermark block generation -----------------------------------------------

def _build_watermark_block(bitstring: str) -> list[str]:
    """
    Produce the list of Verilog source lines that form the watermark region.

    Format
    ------
    // SHIPP_WATERMARK_BEGIN bits=<N>
    localparam [63:0] _wm_0000 = 64'b<64-bit chunk>;
    ...
    // SHIPP_WATERMARK_END

    The final chunk is zero-padded on the right to 64 bits if the total bit
    count is not a multiple of BITS_PER_LINE.  The exact original bit count
    is stored in the BEGIN tag so the extractor can trim trailing padding.
    """
    n      = len(bitstring)
    lines  = [f"    // {WATERMARK_BEGIN_TAG} bits={n}"]

    # Pad to a multiple of BITS_PER_LINE
    remainder = n % BITS_PER_LINE
    padded    = bitstring + ('0' * ((BITS_PER_LINE - remainder) % BITS_PER_LINE))
    num_chunks = len(padded) // BITS_PER_LINE

    for i in range(num_chunks):
        chunk = padded[i * BITS_PER_LINE : (i + 1) * BITS_PER_LINE]
        name  = f"{PARAM_PREFIX}{i:04d}"
        lines.append(f"    localparam [{BITS_PER_LINE-1}:0] {name} = {BITS_PER_LINE}'b{chunk};")

    lines.append(f"    // {WATERMARK_END_TAG}")
    return lines

# --- Embedding ----------------------------------------------------------------

def embed_watermark(verilog_src: str, bitstring: str) -> str:
    """
    Insert the watermark localparam block into the Verilog module.

    Injection point: just before the first `always` block (or before
    `endmodule` if no `always` is found), inside the module body.

    If a watermark region already exists (from a previous embed), it is
    replaced rather than duplicated.

    Parameters
    ----------
    verilog_src : str   — original Verilog source text
    bitstring   : str   — '0'/'1' bitstream to embed

    Returns
    -------
    str  — modified Verilog source with watermark block inserted
    """
    wm_lines = _build_watermark_block(bitstring)
    wm_block = "\n".join(wm_lines) + "\n"

    # If a watermark already exists, replace it
    existing_pattern = re.compile(
        rf"[ \t]*//\s*{re.escape(WATERMARK_BEGIN_TAG)}.*?//\s*{re.escape(WATERMARK_END_TAG)}[^\n]*\n",
        re.DOTALL
    )
    if existing_pattern.search(verilog_src):
        return existing_pattern.sub(wm_block, verilog_src)

    # Otherwise inject before first `always` block
    always_match = re.search(r"^(\s*always\b)", verilog_src, re.MULTILINE)
    if always_match:
        idx = always_match.start()
        return verilog_src[:idx] + wm_block + "\n" + verilog_src[idx:]

    # Fallback: inject just before endmodule
    end_match = re.search(r"^(\s*endmodule\b)", verilog_src, re.MULTILINE)
    if end_match:
        idx = end_match.start()
        return verilog_src[:idx] + wm_block + "\n" + verilog_src[idx:]

    raise ValueError(
        "Could not find a suitable injection point in the Verilog source.\n"
        "  Expected an 'always' block or 'endmodule' keyword."
    )

# --- Extraction ---------------------------------------------------------------

def extract_watermark(watermarked_src: str) -> str:
    """
    Parse the watermarked Verilog source and reconstruct the original bitstring.

    Extraction steps
    ----------------
    1. Find the SHIPP_WATERMARK_BEGIN line and read the original bit count N.
    2. Collect all localparam lines between BEGIN and END tags.
    3. Parse the binary literal from each localparam and concatenate.
    4. Trim any trailing padding to recover the original N-bit string.

    Parameters
    ----------
    watermarked_src : str — text of the watermarked Verilog file

    Returns
    -------
    str  — extracted '0'/'1' bitstring (trimmed to original length)

    Raises
    ------
    ValueError
        If the watermark region or required tags are missing/malformed.
    """
    # Find BEGIN tag and extract bit count
    begin_match = re.search(
        rf"//\s*{re.escape(WATERMARK_BEGIN_TAG)}\s+bits=(\d+)", watermarked_src
    )
    if not begin_match:
        raise ValueError(
            f"Watermark BEGIN tag '{WATERMARK_BEGIN_TAG}' not found in source."
        )
    original_bits = int(begin_match.group(1))

    # Find END tag
    end_match = re.search(
        rf"//\s*{re.escape(WATERMARK_END_TAG)}", watermarked_src
    )
    if not end_match:
        raise ValueError(
            f"Watermark END tag '{WATERMARK_END_TAG}' not found in source."
        )

    # Extract the region between the tags
    region = watermarked_src[begin_match.end():end_match.start()]

    # Parse all localparam binary literals (order-preserving)
    param_pattern = re.compile(
        r"localparam\s+\[\d+:\d+\]\s+" + re.escape(PARAM_PREFIX) + r"\d{4}\s*=\s*\d+'b([01]+)\s*;"
    )
    chunks = param_pattern.findall(region)

    if not chunks:
        raise ValueError("No watermark localparam lines found between BEGIN and END tags.")

    # Concatenate and trim padding
    full_bits = "".join(chunks)
    return full_bits[:original_bits]

# --- Output -------------------------------------------------------------------

def save_watermarked(watermarked_src: str, rtl_path: str) -> str:
    """Save the watermarked Verilog source to outputs/<stem>_watermarked.v."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    stem     = os.path.splitext(os.path.basename(rtl_path))[0]
    out_path = os.path.join(OUTPUTS_DIR, f"{stem}_watermarked.v")
    with open(out_path, "w") as f:
        f.write(watermarked_src)
    return os.path.abspath(out_path)

# --- High-level entry point ---------------------------------------------------

def embed_and_verify(image_path: str,
                     rtl_path: str = RTL_SOURCE_DEFAULT) -> dict:
    """
    Full Stage 9 flow:
        load bitstream + Verilog → embed watermark → save → extract → round-trip test

    Parameters
    ----------
    image_path : str   — source fingerprint image (for deriving bitstream filename)
    rtl_path   : str   — host Verilog module to watermark

    Returns
    -------
    dict with all metrics for display.
    """
    # 1. Load inputs
    print(f"[*] Loading signature bitstream for: {image_path}")
    bitstring = load_bitstream(image_path)

    print(f"[*] Loading RTL source: {rtl_path}")
    verilog_src = load_verilog(rtl_path)

    orig_lines = verilog_src.count('\n')
    orig_bytes = len(verilog_src.encode())

    # 2. Embed
    print(f"[*] Embedding {len(bitstring)}-bit watermark ...")
    watermarked_src = embed_watermark(verilog_src, bitstring)

    wm_lines = watermarked_src.count('\n')
    wm_bytes = len(watermarked_src.encode())

    # 3. Save
    out_path = save_watermarked(watermarked_src, rtl_path)
    print(f"[+] Watermarked module saved → {out_path}")

    # 4. Extract
    print(f"[*] Extracting watermark from saved file ...")
    with open(out_path, "r") as f:
        saved_src = f.read()
    extracted = extract_watermark(saved_src)

    # 5. Round-trip test — bit-for-bit comparison
    rt_passed = (extracted == bitstring)
    if rt_passed:
        rt_detail = (
            f"Bit-for-bit match confirmed  "
            f"(SHA-256: {hashlib.sha256(bitstring.encode()).hexdigest()})"
        )
    else:
        # Find first differing position
        for i, (a, b) in enumerate(zip(bitstring, extracted)):
            if a != b:
                rt_detail = f"First mismatch at bit index {i}: original='{a}', extracted='{b}'"
                break
        else:
            rt_detail = f"Length mismatch: original {len(bitstring)}, extracted {len(extracted)}"

    return {
        "image_path":    image_path,
        "rtl_path":      rtl_path,
        "bits_embedded": len(bitstring),
        "orig_lines":    orig_lines,
        "orig_bytes":    orig_bytes,
        "wm_lines":      wm_lines,
        "wm_bytes":      wm_bytes,
        "out_path":      out_path,
        "rt_passed":     rt_passed,
        "rt_detail":     rt_detail,
    }

# --- __main__ -----------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "SHIPP Stage 9 — Embed Dilithium signature bitstream into a "
            "Verilog RTL module as a watermark."
        )
    )
    parser.add_argument(
        "--image",
        type=str,
        default="input_images/3.jpg",
        help="Source fingerprint image (used to locate bitstream file, "
             "default: input_images/3.jpg)"
    )
    parser.add_argument(
        "--rtl",
        type=str,
        default=RTL_SOURCE_DEFAULT,
        help=f"Host Verilog module to watermark (default: {RTL_SOURCE_DEFAULT})"
    )
    args = parser.parse_args()

    print("=" * 65)
    print("SHIPP Pipeline — Stage 9: RTL Watermark Embedding")
    print("=" * 65)

    r = embed_and_verify(args.image, args.rtl)

    col = 32
    rt_label = "PASS ✓" if r["rt_passed"] else "FAIL ✗"

    added_lines = r["wm_lines"] - r["orig_lines"]
    added_bytes = r["wm_bytes"] - r["orig_bytes"]

    print()
    print("=" * 75)
    print("EMBEDDING SUMMARY")
    print("=" * 75)
    print(f"  {'Source image':<{col}}: {r['image_path']}")
    print(f"  {'Host RTL module':<{col}}: {r['rtl_path']}")
    print(f"  {'Bits embedded':<{col}}: {r['bits_embedded']} bits  "
          f"({r['bits_embedded'] // 8} bytes)")
    print(f"  {'Encoding':<{col}}: localparam [{BITS_PER_LINE-1}:0], MSB-first, "
          f"{BITS_PER_LINE} bits/line")
    print()
    print(f"  {'Original module':<{col}}: {r['orig_lines']} lines  /  {r['orig_bytes']} bytes")
    print(f"  {'Watermarked module':<{col}}: {r['wm_lines']} lines  /  {r['wm_bytes']} bytes")
    print(f"  {'Size increase':<{col}}: +{added_lines} lines  /  +{added_bytes} bytes")
    print(f"  {'Watermarked file':<{col}}: {r['out_path']}")
    print()
    print(f"  {'Round-trip test':<{col}}: {rt_label}")
    print(f"  {'Round-trip detail':<{col}}: {r['rt_detail']}")
    print("=" * 75)

    if not r["rt_passed"]:
        print(f"\n  [!] Round-trip FAILED: {r['rt_detail']}")
        sys.exit(1)
    else:
        print()
        print("  NOTE: This is a proof-of-concept for embedding feasibility.")
        print("  Synthesis validation and area-impact analysis are future work.")
        print()
        print("  Round-trip extraction confirmed — watermark is losslessly recoverable. ✓")
