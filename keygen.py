"""
keygen.py — Stage 3: Dilithium Key Generation (SHIPP Pipeline)
===============================================================
Generates a post-quantum key pair using CRYSTALS-Dilithium (ML-DSA-65),
standardised as NIST FIPS 204.  Keys are persisted to the keys/ directory
so they can be reused across pipeline runs without regeneration.

Algorithm selection:
  - ML-DSA-65  (≡ Dilithium3 in pre-standardisation notation)
  - Security level: NIST Level 3 (≈ AES-192 classical equivalent)
  - Signature size: 3309 bytes | Public key: 1952 bytes | Private key: 4032 bytes

Dependency:
  liboqs-python 0.16.0+  (pip install liboqs-python)
  The native shared library (liboqs.dll / liboqs.so) must be on PATH / LD_LIBRARY_PATH.
  Windows build instructions:
    git clone --depth=1 https://github.com/open-quantum-safe/liboqs
    cmake -S liboqs -B liboqs/build -G Ninja -DBUILD_SHARED_LIBS=ON
    cmake --build liboqs/build --config Release
    set PATH=<liboqs/build/bin>;%PATH%
"""

import os
import time

# --- Configuration ----------------------------------------------------------

ALGORITHM   = "ML-DSA-65"   # NIST FIPS 204 standardised name for Dilithium3
KEYS_DIR    = "keys"
PUB_KEY_FILE  = os.path.join(KEYS_DIR, "dilithium_public.key")
PRIV_KEY_FILE = os.path.join(KEYS_DIR, "dilithium_private.key")

# --- Dependency guard --------------------------------------------------------

def _import_oqs():
    """
    Import the oqs module with a clear error message if liboqs-python is
    missing or the native shared library cannot be found.
    """
    try:
        import oqs
        return oqs
    except ImportError:
        raise ImportError(
            "liboqs-python is not installed.\n"
            "  Install with:  pip install liboqs-python\n"
            "  The native shared library (liboqs.dll on Windows, liboqs.so on Linux)\n"
            "  must also be on your system PATH / LD_LIBRARY_PATH.\n"
            "  Windows build guide: https://github.com/open-quantum-safe/liboqs#windows"
        )
    except OSError as exc:
        raise OSError(
            "liboqs-python Python wrapper is installed, but the native shared\n"
            "  library (liboqs.dll / liboqs.so) could not be loaded.\n"
            f"  Underlying error: {exc}\n"
            "  Ensure the compiled library is on your PATH (Windows) or\n"
            "  LD_LIBRARY_PATH (Linux/macOS).\n"
            "  Windows build guide: https://github.com/open-quantum-safe/liboqs#windows"
        )

# --- Core functions ----------------------------------------------------------

def generate_keypair() -> tuple[bytes, bytes]:
    """
    Generate a fresh ML-DSA-65 (Dilithium3) public/private key pair.

    Returns
    -------
    public_key : bytes
        The signer's public verification key (1952 bytes for ML-DSA-65).
    private_key : bytes
        The signer's secret key (4032 bytes for ML-DSA-65).  Keep private.

    Notes
    -----
    Key generation uses the oqs.Signature context manager, which internally
    calls OQS_SIG_keypair(), delegating randomness to the platform CSPRNG.
    The context manager ensures the native memory holding the secret key is
    zeroed on exit via OQS_SIG_free().
    """
    oqs = _import_oqs()
    with oqs.Signature(ALGORITHM) as signer:
        public_key  = signer.generate_keypair()   # returns public key; stores secret internally
        private_key = signer.export_secret_key()  # extract private key as bytes
    return public_key, private_key


def save_keys(public_key: bytes, private_key: bytes) -> None:
    """
    Persist a key pair to the keys/ directory in raw binary format.
    Files are overwritten if they already exist.

    File layout
    -----------
    keys/dilithium_public.key   — public verification key (binary)
    keys/dilithium_private.key  — secret signing key      (binary, keep secure)
    """
    os.makedirs(KEYS_DIR, exist_ok=True)
    with open(PUB_KEY_FILE,  "wb") as f:
        f.write(public_key)
    with open(PRIV_KEY_FILE, "wb") as f:
        f.write(private_key)


def load_keys() -> tuple[bytes, bytes]:
    """
    Load a previously generated key pair from disk.

    Returns
    -------
    public_key : bytes
    private_key : bytes

    Raises
    ------
    FileNotFoundError
        If either key file is missing (call generate_and_persist_keys() first).
    """
    if not os.path.exists(PUB_KEY_FILE) or not os.path.exists(PRIV_KEY_FILE):
        raise FileNotFoundError(
            f"Key files not found in '{KEYS_DIR}/'. "
            "Run keygen.py once to generate and persist the keys."
        )
    with open(PUB_KEY_FILE,  "rb") as f:
        public_key = f.read()
    with open(PRIV_KEY_FILE, "rb") as f:
        private_key = f.read()
    return public_key, private_key


def generate_and_persist_keys(force: bool = False) -> tuple[bytes, bytes]:
    """
    High-level helper: generate keys and save them to disk.
    If keys already exist on disk, load and return them unless force=True.

    Parameters
    ----------
    force : bool
        If True, always regenerate even if keys already exist on disk.

    Returns
    -------
    public_key, private_key : bytes
    """
    if not force and os.path.exists(PUB_KEY_FILE) and os.path.exists(PRIV_KEY_FILE):
        print(f"[*] Key files already exist in '{KEYS_DIR}/'. Loading from disk.")
        print(f"    (Pass force=True to regenerate.)")
        return load_keys()

    print(f"[*] Generating {ALGORITHM} key pair...")
    t_start = time.perf_counter()
    public_key, private_key = generate_keypair()
    elapsed_ms = (time.perf_counter() - t_start) * 1000

    save_keys(public_key, private_key)

    print(f"[+] Key generation complete.")
    print(f"    Algorithm    : {ALGORITHM}")
    print(f"    Keygen time  : {elapsed_ms:.2f} ms")
    print(f"    Public key   : {len(public_key)} bytes  → {PUB_KEY_FILE}")
    print(f"    Private key  : {len(private_key)} bytes  → {PRIV_KEY_FILE}")
    return public_key, private_key


# --- __main__ block ----------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("SHIPP Pipeline — Stage 3: Dilithium Key Generation")
    print("=" * 60)

    # Always regenerate when run directly so the summary is fresh.
    pub, priv = generate_and_persist_keys(force=True)

    # Verify round-trip: reload from disk and compare.
    pub_loaded, priv_loaded = load_keys()
    roundtrip_ok = (pub == pub_loaded) and (priv == priv_loaded)

    print()
    print("=" * 60)
    print("KEY GENERATION SUMMARY")
    print("=" * 60)
    col = 20
    print(f"  {'Algorithm':<{col}}: {ALGORITHM}")
    print(f"  {'NIST security level':<{col}}: 3  (≈ AES-192)")
    print(f"  {'Public key size':<{col}}: {len(pub)} bytes  ({len(pub) * 8} bits)")
    print(f"  {'Private key size':<{col}}: {len(priv)} bytes  ({len(priv) * 8} bits)")
    print(f"  {'Public key file':<{col}}: {os.path.abspath(PUB_KEY_FILE)}")
    print(f"  {'Private key file':<{col}}: {os.path.abspath(PRIV_KEY_FILE)}")
    print(f"  {'Disk round-trip':<{col}}: {'PASS ✓' if roundtrip_ok else 'FAIL ✗'}")
    print("=" * 60)
