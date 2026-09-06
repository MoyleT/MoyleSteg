# MoyleSteg Android 0.1.0-alpha — design and scope

Approved direction: Android only, Kotlin core + Kotlin/Jetpack Compose UI. Desktop
Python 1.4.1 is the protocol reference, not bundled into the APK. This is a first
source release, not a claim of audited or device-tested production software.

## Architecture
- `core`: platform-independent Kotlin/JVM. AES-GCM via JCA, scrypt via Bouncy Castle
  lightweight SCrypt, HKDF/HMAC via JCA. Fixed desktop v1 header/payload/layout.
- `core/PngCodec`: bounded non-interlaced 8-bit RGB/RGBA PNG codec. No Android
  Bitmap in the extraction path; preserve RGB even under alpha=0. Unsupported
  PNG modes explicitly reject. No image resampling or metadata color conversion.
- `app`: Compose phone layouts and three existing brand palettes, ViewModel job
  state, system document picker, bounded capture, cancellation, explicit export.
- No networking, analytics, arbitrary shared-storage access, Python runtime, root,
  biometric key vault, automatic background resume, multi-file queues or iOS.

## First release contract
Encrypt/decrypt SAES; hide/extract supported PNG; password and .stegkey import;
key generation/export; preflight capacity; verify captured bytes without exporting
plaintext; keep original/content and container hashes distinct. Existing desktop
PNG outputs (8-bit RGBA, non-interlaced) are in the supported subset.

Limits (initial conservative defaults, not hardware guarantees): payload 4 MiB,
12,000,000 pixels, complete container 64 MiB. Unsupported PNG (palette, grayscale,
16-bit, interlaced, APNG) rejects with a specific message; JPEG/HEIC covers,
auto-enlarge and streaming are outside this first increment. Do not convert a
stego image to work around unsupported decoding.

Credentials are not persisted in saved state or preferences. No internet
permission. Android backups disabled, application work files live in noBackupFilesDir.
One active task; validated output held privately until explicit CreateDocument.
Export readback hashes exactly the bytes written; provider failures are not
reported as success. Documents providers do not guarantee atomic export: partial
new destination is best-effort deleted on failure. Input URI equality and original
content readback guard checked before export; no claim of provider-level snapshot.

## Validation
Use synthetic fixtures generated with the exact desktop source. Kotlin decodes
both credential modes; desktop decodes Kotlin PNG/SAES outputs. Test all filters,
alpha=0 pixels, CRC/tag corruption, boundaries, unicode, false lengths, unsupported
KDF parameters and cancellation. Report JVM vs Android build/device validation
separately. Do not include private user documents, actual secrets, or font files.
