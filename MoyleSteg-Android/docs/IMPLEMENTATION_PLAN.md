# Android first increment implementation plan

Goal: an inspectable source project with a tested v1-compatible Kotlin core and
an Android-only Compose application wired to that core.

1. Generate immutable synthetic compatibility fixtures from desktop 1.4.1 and
   record the reference SHA-256. Write JVM regression cases before the core.
2. Implement credential, bounded parser, AEAD, compression and keyed layout; run
   known-value, negative and cross-language tests after each coherent change.
3. Implement bounded RGB/RGBA PNG filtering without display-pipeline transforms;
   compare all pixels with Pillow, including alpha-zero RGB values.
4. Build Android selection/capture/job/export state and Compose phone forms. Use
   deferred output export, immutable result association and explicit cleanup.
5. Add reproducible Gradle configuration, local JVM runner and Android CI build.
   Attempt build with available tools; report environment gaps precisely.
6. Review code and security boundaries; run final regressions; package source,
   synthetic fixtures and verification logs, never real data or signing keys.
