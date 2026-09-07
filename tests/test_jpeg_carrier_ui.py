"""JPEG carriers exercise the real desktop worker and produce authenticated PNGs."""
from hashlib import sha256
from pathlib import Path
import time

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QMimeDatabase, QTimer
from PySide6.QtWidgets import QFileDialog

import png_steg_aes256 as core
from test_v12_window import create_window


JPEG_CASES = ('normal', 'progressive', 'grayscale') + tuple(
    f'exif-{orientation}' for orientation in range(1, 9)
)
SYNTHETIC_PASSWORD = 'JPEG carrier synthetic regression credential'
_ORIENTATION_TRANSFORMS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def make_jpeg_case(directory, case):
    """Small asymmetric public fixture; expected orientation avoids exif_transpose."""
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (144, 96), '#476583')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 49, 31), fill='#ee2211')
    draw.rectangle((90, 0, 143, 45), fill='#22cc44')
    draw.rectangle((0, 70, 70, 95), fill='#1144dd')
    draw.polygon(((97, 61), (132, 80), (118, 94)), fill='#eedd33')
    if case == 'grayscale':
        image = image.convert('L')
    orientation = int(case.split('-')[1]) if case.startswith('exif-') else 1
    extension = '.jpeg' if case in ('progressive', 'grayscale') else '.jpg'
    carrier = directory / (case + extension)
    options = {'format': 'JPEG', 'quality': 93, 'progressive': case == 'progressive'}
    if case.startswith('exif-'):
        exif = Image.Exif()
        exif[274] = orientation
        options['exif'] = exif
    image.save(carrier, **options)
    image.close()
    with Image.open(carrier) as decoded:
        expected = decoded.convert('RGBA')
    if orientation in _ORIENTATION_TRANSFORMS:
        transposed = expected.transpose(_ORIENTATION_TRANSFORMS[orientation])
        expected.close()
        expected = transposed
    return carrier, expected


def _snapshot(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns, sha256(path.read_bytes()).hexdigest()


def _populate_hide(window, carrier, payload):
    window.show_page('hide')
    form = window.forms['hide']
    form['cover'].edit.setText(str(carrier))
    form['input'].edit.setText(str(payload))
    form['password'].setText(SYNTHETIC_PASSWORD)
    form['confirm'].setText(SYNTHETIC_PASSWORD)
    form['resize'].setChecked(False)
    return form


@pytest.mark.parametrize('case', JPEG_CASES)
def test_jpeg_gui_hide_produces_oriented_authenticated_png_without_changing_inputs(
    qtbot, tmp_path, case
):
    carrier, expected = make_jpeg_case(tmp_path, case)
    payload = tmp_path / 'synthetic-payload.bin'
    payload.write_bytes(bytes(range(256)) * 2)
    originals = {path: _snapshot(path) for path in (carrier, payload)}
    window = create_window(qtbot, tmp_path)
    form = _populate_hide(window, carrier, payload)
    qtbot.waitUntil(lambda: window._dimensions is not None, timeout=5000)
    assert window._dimensions == expected.size
    output = Path(form['output'].edit.text())
    assert output == payload.with_name(payload.stem + '_hidden.png')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=20000)
    assert window.last_result is not None, window.status_label.text()
    assert window.last_result.operation == 'hide'
    assert Path(window.last_result.output_path) == output
    assert window.last_result.details['container_format'] == 'png'
    assert str(output) in window.result_summary.text()
    assert output.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    mime = QMimeDatabase().mimeTypeForFile(str(output), QMimeDatabase.MatchMode.MatchContent)
    assert mime.name() == 'image/png'
    with Image.open(output) as produced:
        assert produced.format == 'PNG' and produced.get_format_mimetype() == 'image/png'
        assert produced.size == expected.size
        assert not produced.getexif()
        # Every RGB channel may change only in its least significant bit; compare
        # the entire asymmetrical image so mirrored EXIF cases cannot pass by size.
        assert bytes(value & 0xFE for value in produced.convert('RGBA').tobytes()) == bytes(
            value & 0xFE for value in expected.tobytes()
        )
    expected.close()
    credential = core.Credential.from_password(SYNTHETIC_PASSWORD)
    decoded = core.decode_image(output, credential=credential)
    assert decoded.filename == payload.name
    assert decoded.data == payload.read_bytes()
    assert decoded.sha256_hex == originals[payload][2]
    with pytest.raises(core.AuthenticationError):
        core.decode_image(output, credential=core.Credential.from_password('wrong synthetic credential'))
    if case == 'normal':
        # One full recovery through GUI buttons complements all carrier variants'
        # real GUI hide path without repeating the same extraction UI eleven times.
        window.show_page('extract')
        restore = window.forms['extract']
        restore['original_name'].setChecked(False)
        restore['input'].edit.setText(str(output))
        restored = tmp_path / 'restored.bin'
        restore['output'].edit.setText(str(restored))
        restore['password'].setText(SYNTHETIC_PASSWORD)
        restore['run'].click()
        qtbot.waitUntil(lambda: not window.busy, timeout=20000)
        assert window.last_result is not None, window.status_label.text()
        assert window.last_result.operation == 'extract'
        assert restored.read_bytes() == payload.read_bytes()
    assert {path: _snapshot(path) for path in originals} == originals
    assert not tuple(tmp_path.glob('.moyle-*'))


def _choose_file(qtbot, window, field, selected):
    """Use the real chooser with a bounded timer tied to this window's dialog."""
    observations, errors = [], []
    deadline = time.monotonic() + 5
    timer = QTimer(window)
    timer.setInterval(20)

    def choose():
        dialogs = [dialog for dialog in window.findChildren(QFileDialog) if dialog.isVisible()]
        if not dialogs:
            return
        dialog = dialogs[-1]
        if time.monotonic() > deadline:
            errors.append('File chooser did not accept the selected synthetic path within 5 seconds.')
            timer.stop()
            dialog.reject()
            return
        try:
            if not observations:
                observations.append((dialog.nameFilters(), dialog.defaultSuffix(), dialog.acceptMode()))
            dialog.selectFile(str(selected))
            dialog.accept()
        except Exception as error:
            errors.append(type(error).__name__)
            timer.stop()
            dialog.reject()

    timer.timeout.connect(choose)
    timer.start()
    try:
        field.browse.click()
    finally:
        timer.stop()
        timer.deleteLater()
    assert not errors, errors
    assert len(observations) == 1
    return observations[0]


@pytest.mark.parametrize('language', ('zh_CN', 'en_US'))
def test_jpeg_chooser_accepts_jpg_and_jpeg_and_save_chooser_adds_png(qtbot, tmp_path, language):
    window = create_window(qtbot, tmp_path)
    window.set_language(language)
    form = window.forms['hide']
    for case in ('normal', 'progressive'):
        carrier, expected = make_jpeg_case(tmp_path, case)
        expected.close()
        filters, _, mode = _choose_file(qtbot, window, form['cover'], carrier)
        assert '*.jpg' in filters[0] and '*.jpeg' in filters[0]
        assert mode == QFileDialog.AcceptMode.AcceptOpen
        assert Path(form['cover'].edit.text()) == carrier
    target_without_suffix = tmp_path / 'selected-output'
    filters, suffix, mode = _choose_file(qtbot, window, form['output'], target_without_suffix)
    assert '*.png' in filters[0]
    assert suffix == 'png' and mode == QFileDialog.AcceptMode.AcceptSave
    assert Path(form['output'].edit.text()) == target_without_suffix.with_suffix('.png')
    assert not target_without_suffix.with_suffix('.png').exists()


def test_jpeg_gui_rejects_jpeg_output_extension_without_writing(qtbot, tmp_path):
    carrier, expected = make_jpeg_case(tmp_path, 'normal')
    expected.close()
    payload = tmp_path / 'synthetic.bin'
    payload.write_bytes(b'An output JPEG cannot preserve the PNG LSB payload.')
    originals = {path: _snapshot(path) for path in (carrier, payload)}
    window = create_window(qtbot, tmp_path)
    window.set_language('en_US')
    form = _populate_hide(window, carrier, payload)
    invalid_output = tmp_path / 'invalid-output.jpg'
    form['output'].edit.setText(str(invalid_output))
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=20000)
    assert window.last_result is None
    assert not invalid_output.exists()
    assert '.png' in window.status_label.text().lower()
    assert {path: _snapshot(path) for path in originals} == originals
    assert not tuple(tmp_path.glob('.moyle-*'))
