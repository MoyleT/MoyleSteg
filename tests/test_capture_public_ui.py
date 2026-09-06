"""Public UI illustrations must use synthetic data and exact output names."""
from importlib import import_module

import pytest
from PySide6.QtCore import QSettings, QSignalBlocker
from PySide6.QtGui import QImage


NAMES = {
    'theme-midnight.png', 'theme-blossom.png', 'theme-terminal.png',
    'completion-summary.png', 'compact-large.png',
}


def capture_module():
    return import_module('scripts.capture_public_ui')


def test_public_capture_generates_only_five_real_qt_demo_images(qapp, tmp_path, monkeypatch):
    capture = capture_module()
    from moyle_steg import service, recovery

    def no_file_operations(*args, **kwargs):
        pytest.fail('Public illustration unexpectedly accessed an input or ran a task')

    monkeypatch.setattr(service, 'execute', no_file_operations)
    monkeypatch.setattr(recovery, 'probe_recovery_resources', no_file_operations)
    report = capture.generate_public_screenshots(tmp_path)
    output = tmp_path / 'docs/screenshots'
    assert {path.name for path in output.iterdir()} == NAMES
    assert report['synthetic_demo'] is True
    assert report['verification_performed'] is False
    assert {item['name'] for item in report['images']} == NAMES
    for item in report['images']:
        image = QImage(str(output / item['name']))
        assert not image.isNull()
        assert image.width() >= 640 and image.height() >= 400
        assert image.textKeys() == []
        assert (image.width(), image.height()) == (item['width'], item['height'])
        assert item['demo_label_visible'] is True
    assert QImage(str(output / 'theme-midnight.png')) != QImage(str(output / 'theme-blossom.png'))
    assert QImage(str(output / 'theme-midnight.png')) != QImage(str(output / 'theme-terminal.png'))


@pytest.mark.parametrize('private_kind', ['path', 'password', 'key', 'label', 'unapproved_demo_path'])
def test_public_state_guard_rejects_private_content_before_capture(qtbot, tmp_path, private_kind):
    capture = capture_module()
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'isolated.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    capture.prepare_scene(window, 'midnight')
    window.show()
    if private_kind == 'label':
        window.status_label.setText('C:/Users/Private/Sensitive/report.json')
    elif private_kind == 'unapproved_demo_path':
        window.preview_details.setText('C:/MoyleDemo/unapproved-private-file.txt')
    else:
        field = {'path': window.forms['hide']['input'].edit,
                 'password': window.forms['hide']['password'],
                 'key': window.forms['hide']['key'].edit}[private_kind]
        with QSignalBlocker(field):
            field.setText('private-demo-secret' if private_kind == 'password' else 'C:/Users/Private/Sensitive/file.txt')
    with pytest.raises(ValueError, match='public|Public'):
        capture.assert_public_data(window)


def test_completion_scene_is_explicitly_a_demo_with_fixed_context(qtbot, tmp_path):
    capture = capture_module()
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'isolated.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    capture.prepare_scene(window, 'completion')
    result = window.last_result
    assert result.input_path == 'C:/MoyleDemo/hidden.png'
    assert result.output_path == 'C:/MoyleDemo/restored/example.txt'
    assert result.completed_at == '2026-01-01T12:00:00+00:00'
    assert '演示' in window.result_summary.text()
    assert 'not verification evidence' in window.status_label.text()
    assert not window.details_toggle.isChecked()
    assert not window.busy
    capture.assert_public_data(window)


def test_existing_public_outputs_are_preserved_by_default(qapp, tmp_path):
    capture = capture_module()
    output = tmp_path / 'docs/screenshots'
    output.mkdir(parents=True)
    saved = output / 'theme-midnight.png'
    saved.write_bytes(b'existing public illustration')
    with pytest.raises(FileExistsError):
        capture.generate_public_screenshots(tmp_path)
    assert saved.read_bytes() == b'existing public illustration'
    assert {path.name for path in output.iterdir()} == {'theme-midnight.png'}
