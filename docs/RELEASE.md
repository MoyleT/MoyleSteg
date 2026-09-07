# Windows 1.6.0 multi-file release

Current multi-file creation, selective recovery, retained-session retry and protocol limits are documented in [MULTIFILE_1.6.0.md](MULTIFILE_1.6.0.md). Earlier retry and responsiveness changes are documented in [RELIABILITY_1.5.1.md](RELIABILITY_1.5.1.md). GIF format and earlier validation are documented in [GIF_1.5.0.md](GIF_1.5.0.md). The archive includes both carrier and bundle parsers. Earlier versioned reports remain historical.

## Public release contents

This document describes current packaging policy. Earlier versioned documents retain their historical release-specific results.

## Source and executable validation status

The inherited 1.4.1 behavior binds restoration budgets to the actual opened container and fixes long-token overflow in narrow result cards. Existing themes, progress effects, captured-data verification association and v1 container/key formats remain compatible.

Current implementation and release verification scope are recorded in [MULTIFILE_1.6.0.md](MULTIFILE_1.6.0.md). Source tests, native interaction, offscreen scaling and frozen-EXE checks are separate runs, using synthetic data. Their counts are not added together or presented as third-party audit results. Qt accessibility-name checks are not complete screen-reader certification. Raw local diagnostic JSON and screenshots remain outside the archive; the five explicitly approved public illustrations below are separate synthetic demonstration scenes, not verification evidence.

## Prepare and package locally

1. Run the supported `scripts/run_tests.py` entry or `运行测试.bat`. The complete suite uses `requirements-test.txt` and the application's Fusion style. See `README_DESKTOP.md` for core-only and native Windows test options.
2. Generate public illustrations with `scripts/capture_public_ui.py` (`--force` to replace those five named images), then run `Build-Desktop.ps1` on Windows. The build creates `dist/MoyleSteg`, copies named public notices/documents, and writes `RELEASE_VERSION.txt` and an exact runtime manifest.
3. Run the newly built EXE's opt-in `--self-test`, directing its JSON and screenshots to a separate local report directory. Even synthetic reports can contain absolute machine paths.
4. After validation, package locally:

```powershell
.\.venv\Scripts\python.exe scripts\package_project.py --output dist\MoyleSteg-1.6.0-Full-Project.zip
```

The command makes no network requests. It refuses to replace an existing archive unless `--force` is explicitly supplied. The source and portable version markers must agree; that stale-build check is not a substitute for running the EXE.

## Explicit public allowlist

Approved root files include `.gitignore`, `gif_carrier.py`, `moyle_bundle.py` and `requirements-test.txt`. Non-recursive rules select `moyle_steg/*.py`, test modules, explicitly named scripts/assets/licenses and ten public documents: `RELEASE.md`, `SECURITY_FIXES_1.2.md`, `RELIABILITY_1.2.1.md`, `VERIFICATION_1.2.2.md`, `APPEARANCE_1.3.0.md`, `RECOVERY_1.4.0.md`, `RELIABILITY_1.4.1.md`, `GIF_1.5.0.md`, `RELIABILITY_1.5.1.md`, `MULTIFILE_1.6.0.md`. Clean builds copy these documents into the runtime; the GIF and multi-file protocol documents are required in both locations.

Only five named images under `docs/screenshots/` are published: `theme-midnight.png`, `theme-blossom.png`, `theme-terminal.png`, `completion-summary.png`, `compact-large.png`. These native Qt illustrations contain fixed synthetic data, empty credentials and a visible demo notice, with no PNG text metadata. They are included only as source documentation. The portable runtime does not duplicate them; screenshot links in its copied documents refer to the full source package's gallery.

Nine theme arrow/checkmark SVGs and the two generated face-free fruit PNGs are explicitly allowlisted. Both fruit assets are required in `assets/` and the runtime's `_internal/assets/`. Adding a document or data directory to the checkout does not automatically publish it.

The clean build records exact portable members, sizes and SHA-256 digests in `dist/MoyleSteg/RUNTIME_MANIFEST.json`. Packaging requires that inventory, validates hashes again while copying bytes, and refuses extra, missing or changed files. Diagnostic outputs at the runtime root, inside a new directory or under `_internal` cannot silently enter a release. Keep `_internal/base_library.zip`: it is a required Python component.

The allowlist excludes `artifacts`, private data directories, `.git`, `.venv`, build/cache directories, local investigation reports, previous release ZIPs and unapproved files. Real `.stegkey` and `.saes` files are excluded. Named synthetic fixtures are limited to `legacy-v1.png`, `legacy-v1.saes`, `legacy-posix-name.saes` in `tests/fixtures/`, plus `kotlin-bundle.zip` and `kotlin-expected.json` in `tests/fixtures/bundle/` for cross-language bundle validation.

## Verify the current archive

The archive contains one `MoyleSteg-1.6.0` root and a `RELEASE_MANIFEST.json` with relative paths, sizes and SHA-256 digests for every payload member. The manifest excludes its own digest and records no build hostname, username, absolute project path or wall-clock timestamp. Verify exact membership and bytes without extracting:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.package_project import verify_public_archive; verify_public_archive(Path('dist/MoyleSteg-1.6.0-Full-Project.zip')); print('Manifest verified')"
```

Members use sorted names and fixed timestamps/attributes. The same approved input bytes produce identical ZIP bytes with the same Python/zlib environment. This does not promise byte-identical EXEs from separate compiler/PyInstaller runs. The manifest is an integrity record, not a digital signature or publisher identity proof. Execute the extracted portable app from its own directory as a separate release smoke check.

## Original baseline and resource scope

`SHA256SUMS.txt` preserves the imported v1.0 baseline. It cannot establish that current files are unchanged. The baseline remains in maintainer Git history at `1e3026a73822e65d236e2f2b158713262f8705b1`; the public archive omits `.git` and does not duplicate the old source ZIP. `PROJECT_OVERVIEW.md` and `README_AES256_三合一.md` are labeled historical baseline documents.

Desktop/service defaults are 25,000,000 pixels, 256 MiB payload and 512 MiB for a complete recovery container. Input selection triggers a background size/temporary-space probe. At recovery start, the worker probes again and displays the result before proceeding. Immediately before verification/information capture, the service independently rechecks budgets and free space, requiring the input size plus a 16 MiB reserve. Displayed disk availability does not reserve that space; these checks do not guarantee peak memory. Authentication and both digests use one private encrypted copy; PNG decoding and payload processing remain memory-based. Capture is not an OS-level snapshot. See [RECOVERY_1.4.0.md](RECOVERY_1.4.0.md) for GUI ceilings, confirmation rules and result semantics.

Extraction/decryption additionally enforce the budget on the actual opened handle and bound PNG/SAES reads in both restoration modes. These guards require no extra full container copy and do not promise an immutable filesystem snapshot. See the current reliability document for the precise boundary and optional core API keyword.
