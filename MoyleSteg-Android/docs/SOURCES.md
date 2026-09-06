# Sources and provenance

## User-provided basis
- MoyleSteg-1.4.1-Full-Project.zip: exact desktop protocol source and theme palette.
- Only desktop core source was copied; no private PDF, real credentials, fonts,
  screenshots, Windows executable or private diagnostic files were copied into this package.

## Official documentation checked during implementation (2026-09-06)
- Android AGP 8.13 compatibility: https://developer.android.com/build/releases/agp-8-13-0-release-notes
- Kotlin 2.2.21 plugin: https://plugins.gradle.org/plugin/org.jetbrains.kotlin.android/2.2.21
- Compose BOM and compiler separation: https://developer.android.com/develop/ui/compose/bom
- Activity versions: https://developer.android.com/jetpack/androidx/releases/activity
- Lifecycle versions: https://developer.android.com/jetpack/androidx/releases/lifecycle
- Storage Access Framework: https://developer.android.com/training/data-storage/shared/documents-files
- Android Cipher: https://developer.android.com/reference/javax/crypto/Cipher
- BC distribution and release notes: https://www.bouncycastle.org/download/bouncy-castle-java/
- Gradle checksums: https://gradle.org/release-checksums/

Versions were pinned rather than blindly selecting the latest Compose BOM, because
newer Compose releases can require newer AGP and compileSdk. Android dependency
resolution is still unverified here. Sources do not substitute for building the app.
