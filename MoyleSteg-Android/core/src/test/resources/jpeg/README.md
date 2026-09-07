# Synthetic JPEG carriers

Pillow-generated 60 × 40 RGB images with six 20 × 20 color tiles. No real photo,
device metadata, GPS or private files are included. `six-colors.jpg` is baseline
JPEG; `progressive.jpg` uses progressive scans. `orientation-6.jpg` adds only EXIF
orientation 6 to the baseline image. All use quality 100 and disabled chroma
subsampling. Tests construct other orientation entries independently in memory.

The independent 144 × 96 fixtures (`normal.jpg`, `progressive.jpeg`,
`grayscale.jpeg`, `exif-1.jpg` through `exif-8.jpg`) use asymmetric colored shapes
and quality 93. Their oriented display size swaps axes for EXIF 5–8. They are
generated with the same `make_carrier` procedure in `tools/generate_jpeg_vectors.py`.
That tool regenerates the Windows PNGs in `interop/`, which documents its public
test-only credentials.

These fixtures enter JVM tests and the separate instrumentation test APK only;
they are not packaged as assets in the normal application APK.
