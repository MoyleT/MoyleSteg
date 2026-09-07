# Desktop v1 compatibility notes

Source of truth: `tools/reference/desktop_1_4_1.py`, extracted without modification
from the user-supplied MoyleSteg-1.4.1-Full-Project.zip. See verification/reference.json
for its hash. Do not substitute earlier conversation summaries for this source.

## Public header

54 bytes: 50-byte big-endian core `>8sBBBBBB16s12sQ`, followed by big-endian CRC32.
Magic `SGAES001`, version=1, mode=1(password)/2(key), scrypt logN/r/p=15/8/1 for
password and 0/0/0 for key, layout=1, salt=16 bytes, nonce=12 bytes, ciphertext
length includes the full 16-byte GCM tag. The 50-byte core is AES-GCM AAD; CRC32 is
not the cryptographic authenticator. Reject unknown KDF parameters before deriving.

Password is strictly UTF-8 encoded. scrypt N=32768,r=8,p=1,dkLen=32. Key-file mode
uses the raw 32-byte key. HKDF-SHA256 salt=header salt, info=
`PNG-STEG-AES256/v1/enc-and-layout`, output=64 bytes split encryption/layout 32/32.

## Encrypted body

Fixed header `>4sBBHQQ32s` (56 bytes): PAY1, version1, compression0/1, UTF-8 name
length, original length, stored length, SHA-256(original). Then basename then
stored bytes. Compression is ordinary zlib wrapper, used only when shorter than
original. Verify GCM first, enforce limits before decompression and reject excess
output, unfinished streams or trailing compressed bytes. Authenticated legacy
basenames unsuitable for Windows can be inspected but export gets a safe suggestion.

## PNG RGB-LSB

Work on 8-bit unpremultiplied RGBA sample bytes, skip alpha. Logical index i maps
into RGBA offset (i/3)*4+(i%3). First 432 RGB channels carry the 54-byte header MSB
first. Remaining channel domain carries ciphertext using the desktop v1 distribution.

Split domain into blocks of 4096 channels. Block receives floor(needed*end/total)
minus floor(needed*start/total) bits. In each block use partial Fisher–Yates, driven
by HMAC-SHA256(key, context||u64counter). Context is ASCII
`PNG-STEG-AES256/layout-block/` followed by u64(block index). Counter starts at zero
per block. `randbelow` uses ceil(upper.bit_length()/8), with rejection to avoid
modulo bias; the power-of-256 case matters. The known-value tests cover it.

The Android port deliberately supports a narrower PNG input set, not a new steg
format. No color conversion, alpha premultiplication, resampling or thumbnail input
is allowed in extraction. It does not preserve ICC/EXIF/ancillary metadata on output.

## Protocol vs output bytes

New salts/nonces and PNG compressor differences legitimately change containers.
Successful compatibility means both sides recover identical name and payload bytes,
not that independently generated encrypted PNGs have identical file hashes.

## Managed multi-file payloads (Android 0.4.0 / Windows 1.6.0)

The existing PAY1 payload may contain a standard ZIP named `MoyleSteg-files.zip`.
Exact EOCD comment `MOYLESTEG-BUNDLE-V1` opts into bounded multi-file inspection;
ordinary ZIP files remain single payloads. This does not change the authenticated
outer format. Older readers recover the complete ZIP. The shared restricted ZIP
profile and recovery semantics are specified in [MULTIFILE_0_4_0.md](MULTIFILE_0_4_0.md).
