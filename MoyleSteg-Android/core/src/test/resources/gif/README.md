# Synthetic GIF regression fixtures

These are generated test images and payloads, with no personal files or production credentials.

- `cover.gif`: Pillow-generated 8 × 6 animation, 3 frames; delays 40/90/120 ms, loop count 2, transparency index 3, disposal modes 1/2/3.
- `dictionary-growth.gif`: Pillow-generated 96 × 96 indexed image, deterministic random palette indices; exercises GIF LZW dictionary growth and clearing.
- `interop/gif-key.gif`, `interop/gif-password.gif`: produced by the Python desktop GIF implementation. Both recover the authenticated original name `synthetic-gif.bin` and exactly the bytes in `interop/source.bin`.

Public test key: the 32 bytes `00 01 02 ... 1f`.
Public test password: `synthetic-gif-password`.

Test vectors are packaged in the source distribution only. They are not application assets and must never be used to protect real files.
