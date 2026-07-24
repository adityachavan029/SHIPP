# SHIPP — Fingerprint Minutiae-to-Bitstream Pipeline

A from-scratch Python implementation of a fingerprint minutiae extraction and binary encoding pipeline, built as the first stage of the **Secure Hardware IP Protection (SHIPP)** post-quantum framework.

## Pipeline Stages

```
Raw Image → Preprocessing → Binarization → Zhang-Suen Thinning
         → Minutiae Detection → Spurious Removal → Orientation
         → Binary Encoding → Bitstream + PDF Report
```

## Features
- **Auto-inversion** — detects dark-background fingerprints and normalises automatically
- **Adaptive equalization** — bypasses global histogram equalization for images with large uniform borders
- **Zhang-Suen thinning** — fully from-scratch implementation
- **Crossing Number minutiae detection** — ridge endings (CN=1) and bifurcations (CN=3)
- **PDF report generation** — styled table with colour-coded binary codes, full bitstream, and statistics

## Usage

```bash
# Run pipeline on a fingerprint image
python main.py --image input_images/1.jpg

# Run on default mock fingerprint (auto-generated)
python main.py

# Skip PDF report
python main.py --image input_images/1.jpg --no-pdf
```

## Project Structure

```
SHIPP/
├── input_images/          # Input fingerprint images
├── output_images/         # Generated outputs (images + PDF report)
├── preprocessing.py       # Normalization, equalization, binarization
├── thinning.py            # Zhang-Suen skeletonization
├── minutiae.py            # CN detection, spurious removal, orientations
├── encoding.py            # Binary encoding and bitstream generation
├── report.py              # PDF report generator (ReportLab)
└── main.py                # Pipeline orchestrator
```

## Requirements

```bash
pip install numpy opencv-python reportlab
```
