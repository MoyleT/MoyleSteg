# Public synthetic JPEG carrier interoperability vectors

These are test data, never credentials for private files. Eleven synthetic JPEG carriers (normal, progressive, grayscale, and EXIF orientations 1 through 8) were hidden using the desktop public hide_file API in key and password modes. Every resulting file is PNG, not JPEG.

* cases.tsv is UTF-8 with a header: name, width, height, key_png, password_png.
* width/height are the dimensions after applying EXIF orientation.
* source.bin contains bytes(range(256)) repeated twice (512 bytes).
* The authenticated original filename is jpeg-互通.bin.
* synthetic.stegkey encodes the 32 public bytes 0 through 31.
* password.txt contains the public password Synthetic JPEG interop 2026!
* Generator desktop module: png_steg_aes256.py; SHA-256: 9ecada37ec7a90e24429a83b399b67da6b112d35efdf90b6e947b4a002d3edd3.

From the Android project, run python tools/generate_jpeg_vectors.py. An adjacent current desktop checkout is used when available; otherwise the bundled tools/reference/desktop_1_5_0.py is used. --desktop-root selects a desktop checkout; --jpeg-dir can reuse the shared synthetic JPEG directory. The default regenerates the same carrier designs without importing desktop tests.

Salts and nonces remain random, so regeneration changes ciphertext bytes. The expected payload, name, dimensions, formats and authentication remain identical.
