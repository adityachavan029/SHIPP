## SHIPP Pipeline Benchmark Results

Algorithm: **ML-DSA-65**  
Times in milliseconds (ms). All stages measured with `time.perf_counter()`.

| Image | Minutiae | Bits | S1 ext (ms) | S3 sign (ms) | S4 ver (ms) | S5 tamp (ms) | S6 conv (ms) | S7 emb (ms) | Total (ms) | Verify | Tamper | BC RT | WM RT |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| 1.jpg | 26 | 728 | 829.19 | 7.45 | 0.73 | 0.27 | 1.71 | 2.13 | 880.81 | ✓ | ✓ | ✓ | ✓ |
| 3.jpg | 37 | 1036 | 945.85 | 1.01 | 0.39 | 0.30 | 1.59 | 0.86 | 983.60 | ✓ | ✓ | ✓ | ✓ |
| 38457.png | 50 | 1400 | 5807.91 | 1.47 | 0.37 | 0.25 | 1.68 | 2.00 | 5861.98 | ✓ | ✓ | ✓ | ✓ |
| image.png | 17 | 476 | 483.33 | 0.84 | 0.45 | 0.26 | 1.48 | 0.73 | 519.18 | ✓ | ✓ | ✓ | ✓ |
| **Mean** | 32.50 | 910 | 2016.57 | 2.69 | 0.48 | 0.27 | 1.61 | 1.43 | 2061.39 | 1 | 1 | 1 | 1 |
