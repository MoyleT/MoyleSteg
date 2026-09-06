# Android device acceptance — pending, not passed

This checklist describes evidence still needed before a device-validated release.
It is not a claim that the listed behaviors were tested in this environment.

The exact Gradle/Kotlin/BC/AndroidX debug build and host regressions passed for
0.2.0-alpha. The current run passed 31 Robolectric tests (4 GIF flow tests),
72 base / 26 capture / 24 expansion / 43 GIF core regressions, five independent
PNG memory scenarios, and three fingerprint vectors. Both debug APKs were built;
neither was installed on an Android device or emulator during this run.
See [the current report](../verification/TEST_REPORT_0_2_0.md).

GIF cross-platform checks passed for both credentials in both directions. The
fresh Kotlin GIF outputs also preserve original animation blocks and Pillow-decoded
frame RGBA, delay, disposal and loop values. These checks can be repeated after
`:core:check` with:

```powershell
py -3 .\tools\verify_gif_python.py .\core\build\gif-output
```

This uses the bundled desktop 1.5.0 reference and requires Pillow and cryptography.
It is a host file/decoder check, not an Android playback or SAF test.

The following device checks remain:

- Run DeviceInteropTest on at least API26 and a current device; exercise actual
  Android AES-GCM provider and scrypt, not only desktop JCA.
- Run UiSmokeTest; test phone widths 320/360/412dp, landscape, font scales1.0/1.5/2.0,
  keyboard visibility, TalkBack labels and touch targets. No screenshot yet rendered.
- Verify stock documents provider, removable USB storage, and a trusted cloud provider.
  Sizes may be unknown; output may be readable later or may fail. Never report such
  failure as successful verified export. Test two equal filenames in different URIs.
- Exercise empty/new/existing destinations, URI aliases, revoked grants, low storage,
  read failures, partial writes, readback mismatch and delete-not-supported failures.
- Interrupt during KDF, compression, pixel IO, save and export. Kill/relaunch process,
  rotate activity, lock device. Verify no false result, no retained shared plaintext
  on failed verification, and documented handling of provider-created partial files.
- Verify real PNGs across supported filters/color types, malformed files and budget
  edges. Unsupported formats must not fall back to lossy Bitmap extraction.
- Measure peak memory/time on representative midrange hardware before changing limits.
- Check the default auto-expansion switch, planned dimensions and enough-capacity path.
  Hide into a tiny synthetic carrier, restore on desktop, then disable expansion and
  confirm a capacity refusal. Cancel while resizing; confirm original inputs remain unchanged.
- Test animated GIF import, image/gif SAF export, frame/loop preservation, and
  cross-platform restoration with desktop 1.5.0 using both password and key files.
  Confirm GIF capacity uses output bytes, automatic PNG expansion never resizes GIF,
  and malformed or oversized animations produce clear refusals. Check playback using
  a real Android viewer after export; no Android playback was exercised in this run.
- Re-run a dependency/security review before signing a release. Do not publish the
  public fixture key, or generated debug signing key, as a user's key or release key.

No biometric vault, background-resume contract, queue or multi-file
container is implemented. These are out of scope, not hidden stubs.

