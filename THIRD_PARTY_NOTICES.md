# Third-party notices

This application uses the following unmodified third-party runtime components. Installed package versions are recorded in `requirements-lock.txt`. Their distributed notices are collected under `_internal/third_party_licenses/` in the portable build.

| Component | Upstream | License information |
|---|---|---|
| Python | https://www.python.org/ | Python Software Foundation license and included notices |
| PySide6 Essentials, Shiboken6, Qt | https://github.com/pyside/pyside-setup | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, or applicable Qt commercial terms, according to the installed package metadata; Qt modules also contain third-party components |
| Pillow | https://github.com/python-pillow/Pillow | HPND and included third-party notices |
| cryptography | https://github.com/pyca/cryptography | Apache-2.0 OR BSD-3-Clause, plus bundled component notices including OpenSSL |
| cffi | https://github.com/python-cffi/cffi | MIT and included notices |
| PyInstaller bootloader | https://github.com/pyinstaller/pyinstaller | GPL with the bootloader exception; see its COPYING.txt |

PySide6/Qt is shipped as replaceable dynamic libraries in the portable directory. The installed Qt for Python source version is 6.11.2: https://github.com/pyside/pyside-setup/tree/v6.11.2 . Qt source downloads and component licensing information are available from https://download.qt.io/official_releases/qt/ and https://doc.qt.io/qt-6/licensing.html . Supplemental LGPL/GPL texts from the same PySide source tag accompany the collected package notices because the wheel's listed License-File includes only its commercial-license notice.

Development-only tools include pytest and pytest-qt; they are excluded from the application executable. The UI and adapters in this project were written for this application; no third-party example implementation was copied.

The 1.3.0 appearance work consulted [Impeccable by Paul Bakaus](https://github.com/pbakaus/impeccable) and [Anthropic's frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design) for design principles covering visual hierarchy, deliberate color, spacing and purposeful motion. Their code, assets, hooks and runtimes are not included in this distribution, and neither is an application dependency. The references and their application to this desktop UI are documented in `docs/APPEARANCE_1.3.0.md`. Earlier local research notes are excluded from public packaging.

The Blossom theme includes `assets/strawberry-sticker.png` and `assets/cherry-sticker.png`, generated for this project with the built-in ImageGen tool and edited to the user's requested face-free style with transparent alpha. The final PNGs are copied unchanged into the project. These are bundled local UI images; the app does not call ImageGen or download the images at runtime. The final generation and editing brief is recorded in `docs/APPEARANCE_1.3.0.md`. They are not Impeccable assets or imported third-party example images.

This notice does not assign a new license to the original project or the user's own code and files.

## GIF format

GIF carrier parsing follows the CompuServe GIF89a format, as hosted at https://www.w3.org/Graphics/GIF/spec-gif89a.txt. The Graphics Interchange Format is the copyright property of CompuServe Incorporated; GIF is a service mark of CompuServe Incorporated. The application-extension and LZW validation implementations in this project are project code, not copied reference decoder source.
