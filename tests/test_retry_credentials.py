"""Real desktop retry flows retain form credentials until the using job succeeds."""
from pathlib import Path
import random

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from moyle_steg.service import OperationRequest, execute
from moyle_steg.window import MainWindow


SECRET = 'synthetic retry-only test credential'


def make_window(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'retry.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    return window


def fill_credentials(window):
    expected = {}
    for page, form in window.forms.items():
        if 'password' in form:
            expected[page] = (f'synthetic-{page}-password', f'synthetic-{page}-confirmation')
            form['password'].setText(expected[page][0])
            form['confirm'].setText(expected[page][1])
    return expected


def assert_credentials(window, expected, cleared=None):
    for page, values in expected.items():
        form = window.forms[page]
        assert (form['password'].text(), form['confirm'].text()) == (('', '') if page == cleared else values)


def wait_finished(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy, timeout=20000)


def hide_inputs(window, tmp_path, size=4096):
    source = tmp_path / 'synthetic.bin'
    source.write_bytes(random.Random(521).randbytes(size))
    cover = tmp_path / 'small-cover.png'
    Image.new('RGB', (32, 32), '#427561').save(cover)
    form = window.forms['hide']
    form['cover'].edit.setText(str(cover))
    form['input'].edit.setText(str(source))
    form['output'].edit.setText(str(tmp_path / 'hidden.png'))
    form['password'].setText(SECRET)
    form['confirm'].setText(SECRET)
    form['resize'].setChecked(False)
    return form


def test_failed_destination_can_be_corrected_without_retyping(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    window.show_page('crypt')
    source = tmp_path / 'synthetic.txt'
    source.write_bytes(b'file-path retry fixture')
    form = window.forms['crypt']
    form['input'].edit.setText(str(source))
    form['output'].edit.setText('relative-output.saes')
    form['password'].setText(SECRET)
    form['confirm'].setText(SECRET)
    expected['crypt'] = (SECRET, SECRET)
    form['run'].click()
    wait_finished(qtbot, window)
    assert window.last_result is None
    assert_credentials(window, expected)
    target = tmp_path / 'valid-output.saes'
    form['output'].edit.setText(str(target))
    form['run'].click()
    wait_finished(qtbot, window)
    assert target.is_file() and window.last_result.operation == 'encrypt'
    assert_credentials(window, expected, cleared='crypt')


def test_capacity_failure_then_enable_expansion_keeps_password_until_success(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    form = hide_inputs(window, tmp_path)
    expected['hide'] = (SECRET, SECRET)
    form['run'].click()
    wait_finished(qtbot, window)
    assert window.last_result is None and not (tmp_path / 'hidden.png').exists()
    assert_credentials(window, expected)
    form['resize'].setChecked(True)
    form['run'].click()
    wait_finished(qtbot, window)
    assert (tmp_path / 'hidden.png').is_file() and window.last_result.operation == 'hide'
    assert_credentials(window, expected, cleared='hide')


@pytest.mark.parametrize('payload_bytes,fits', [(128, 'yes'), (4096, 'no')])
def test_preflight_result_preserves_all_pages_for_retry(qtbot, tmp_path, payload_bytes, fits):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    form = hide_inputs(window, tmp_path, payload_bytes)
    expected['hide'] = (SECRET, SECRET)
    form['preflight'].click()
    wait_finished(qtbot, window)
    assert window.last_result.operation == 'preflight'
    assert window.last_result.details['fits'] == fits
    assert_credentials(window, expected)


@pytest.mark.parametrize('field_name', ['input', 'output'])
def test_cancel_file_chooser_preserves_path_and_credentials(qtbot, tmp_path, field_name):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    window.show_page('crypt')
    field = window.forms['crypt'][field_name]
    selected = str(tmp_path / ('existing.bin' if field_name == 'input' else 'chosen.saes'))
    field.edit.setText(selected)
    observed = []

    def cancel_dialog():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QFileDialog)
        observed.append(dialog)
        dialog.reject()

    QTimer.singleShot(0, cancel_dialog)
    field.browse.click()
    assert observed and not window.busy
    assert field.edit.text() == selected
    assert_credentials(window, expected)


def test_key_generation_does_not_clear_unrelated_credentials(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    window.show_page('keygen')
    window.forms['keygen']['output'].edit.setText(str(tmp_path / 'new.stegkey'))
    window.forms['keygen']['run'].click()
    wait_finished(qtbot, window)
    assert window.last_result.operation == 'keygen'
    assert_credentials(window, expected)


@pytest.mark.parametrize('operation', ['hide', 'encrypt', 'extract', 'decrypt', 'verify', 'inspect'])
def test_success_clears_only_page_used_by_authenticated_operation(qtbot, tmp_path, operation):
    source = tmp_path / 'original.txt'
    source.write_bytes(b'authenticated completion fixture' * 4)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (128, 128), '#527568').save(cover)
    input_path = source
    if operation in {'extract', 'inspect', 'decrypt', 'verify'}:
        encoded_operation = 'hide' if operation in {'extract', 'inspect'} else 'encrypt'
        input_path = tmp_path / ('input.png' if encoded_operation == 'hide' else 'input.saes')
        execute(OperationRequest(encoded_operation, input_path=str(source), cover_path=str(cover),
                                 output_path=str(input_path), password=SECRET, password_confirm=SECRET))
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    page = {'encrypt': 'crypt', 'decrypt': 'crypt', 'inspect': 'extract'}.get(operation, operation)
    window.show_page(page)
    form = window.forms[page]
    if page == 'crypt':
        form['mode'].setCurrentIndex(1 if operation == 'decrypt' else 0)
    form['input'].edit.setText(str(input_path))
    if operation == 'hide':
        form['cover'].edit.setText(str(cover))
    if 'output' in form:
        destination = tmp_path / ('restored' if operation in {'extract', 'decrypt'} else ('result.png' if operation == 'hide' else 'result.saes'))
        form['output'].edit.setText(str(destination))
    form['password'].setText(SECRET)
    form['confirm'].setText(SECRET)
    form['show'].setChecked(True)
    expected[page] = (SECRET, SECRET)
    (form['inspect'] if operation == 'inspect' else form['run']).click()
    window.show_page('guide')
    wait_finished(qtbot, window)
    assert window.last_result is not None and window.last_result.operation == operation
    assert_credentials(window, expected, cleared=page)
    assert not form['show'].isChecked()
    window.settings.sync()
    saved = Path(window.settings.fileName()).read_text(encoding='utf-8')
    assert SECRET not in saved and not any(value in saved for values in expected.values() for value in values)


def test_closing_idle_window_clears_all_page_credentials(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    expected = fill_credentials(window)
    assert window.close()
    assert_credentials(window, {page: ('', '') for page in expected})


def test_explicit_field_clear_is_not_restored_after_preflight(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    form = hide_inputs(window, tmp_path)
    form['password'].clear()
    form['confirm'].clear()
    form['preflight'].click()
    wait_finished(qtbot, window)
    assert window.last_result.operation == 'preflight'
    assert form['password'].text() == form['confirm'].text() == ''
