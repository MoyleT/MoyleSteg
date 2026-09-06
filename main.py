"""Windows desktop entry point. The original CLI remains independently usable."""

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from moyle_steg import __version__
from moyle_steg.fonts import configure_fonts
from moyle_steg.window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="Moyle Steganography Studio")
    parser.add_argument("--language", choices=("zh_CN", "en_US"))
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON",
                        help="Check the packaged runtime with synthetic files and write a report.")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Moyle Steganography Studio")
    app.setOrganizationName("Moyle")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    configure_fonts(app)
    icon = QIcon(str(Path(__file__).resolve().parent / "assets" / "app.svg"))
    app.setWindowIcon(icon)
    if args.self_test:
        from moyle_steg.diagnostics import self_test
        return self_test(app, args.self_test.resolve())
    window = MainWindow()
    window.setWindowIcon(icon)
    if args.language:
        window.set_language(args.language)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
