"""GIF presentation must not reuse PNG-only capacity or overwrite custom paths."""
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QSettings

from moyle_steg.service import OperationResult
from moyle_steg.window import MainWindow


@pytest.fixture
def gif_window(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.set_reduce_motion(True)
    window.show()
    window.forms['hide']['input'].edit.setText(str(tmp_path / 'synthetic.txt'))
    return window


def cover_files(tmp_path):
    png = tmp_path / 'cover.png'
    gif = tmp_path / 'animation.gif'
    image = Image.new('RGB', (16, 16), 'blue')
    image.save(png)
    image.save(gif, save_all=True, append_images=[Image.new('RGB', (16, 16), 'red')], duration=[40, 80], loop=2)
    return png, gif


def test_cover_switch_updates_automatic_suffix_and_png_only_controls(gif_window, tmp_path):
    png, gif = cover_files(tmp_path)
    form = gif_window.forms['hide']
    form['cover'].edit.setText(str(png))
    form['resize'].setChecked(True)
    assert Path(form['output'].edit.text()).suffix == '.png'
    form['cover'].edit.setText(str(gif))
    assert Path(form['output'].edit.text()).suffix == '.gif'
    assert not form['resize'].isEnabled() and not form['fill'].isEnabled()
    gif_window._refresh_preview()
    assert 'LSB' not in gif_window.preview_details.text()
    form['cover'].edit.setText(str(png))
    assert Path(form['output'].edit.text()).suffix == '.png'
    assert form['resize'].isEnabled()
    assert form['fill'].isEnabled()


def test_custom_destination_is_preserved_on_cover_change(gif_window, tmp_path):
    png, gif = cover_files(tmp_path)
    form = gif_window.forms['hide']
    form['cover'].edit.setText(str(png))
    custom = str(tmp_path / 'chosen-explicitly.png')
    form['output'].edit.setText(custom)
    form['cover'].edit.setText(str(gif))
    assert form['output'].edit.text() == custom


def test_cover_change_invalidates_completed_result_and_running_input_revision(gif_window, tmp_path):
    png, gif = cover_files(tmp_path)
    gif_window.forms['hide']['cover'].edit.setText(str(png))
    revision = gif_window._input_versions['hide']
    gif_window.last_result = OperationResult(operation='hide', title='hide_success', details={'filename': 'synthetic.txt'})
    gif_window._result_page = 'hide'
    gif_window._render_result()
    gif_window.forms['hide']['cover'].edit.setText(str(gif))
    assert gif_window.last_result is None
    assert gif_window.result_card.isHidden()
    assert gif_window._input_versions['hide'] > revision


def test_gif_signature_takes_precedence_over_misleading_extension(gif_window, tmp_path):
    _, gif = cover_files(tmp_path)
    disguised = tmp_path / 'actually-a-gif.png'
    disguised.write_bytes(gif.read_bytes())
    gif_window.forms['hide']['cover'].edit.setText(str(disguised))
    assert Path(gif_window.forms['hide']['output'].edit.text()).suffix == '.gif'


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_gif_preflight_reports_frames_and_output_bytes(gif_window, language):
    gif_window.set_language(language)
    gif_window._preflight_result = OperationResult(operation='preflight', details={
        'container_format': 'gif', 'frame_count': '3', 'output_bytes': '4096',
        'fits': 'yes', 'ciphertext_bytes': '1024', 'capacity': '65536',
        'width': '16', 'height': '16', 'estimated_peak_bytes': '8192',
        'resource_level': 'low', 'reason': '',
    })
    gif_window._render_preflight()
    text = gif_window.preflight_label.text()
    assert 'GIF' in text and '3' in text and '4.00 KiB' in text
    assert 'LSB' not in text
