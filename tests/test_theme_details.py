"""Small themed details retain normal file gestures and bounded motion."""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QMimeData, QUrl, QPoint, QPointF, QAbstractAnimation
from PySide6.QtGui import QImage, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from moyle_steg.theme import get_theme, build_stylesheet
from moyle_steg.widgets import FileField, FruitAccent, ImagePreview


@pytest.mark.parametrize('kind', ['strawberry', 'cherry'])
def test_stickers_are_packaged_transparent_artwork(kind):
    image = QImage(str(Path(__file__).resolve().parents[1] / 'assets' / f'{kind}-sticker.png'))
    assert not image.isNull()
    assert image.hasAlphaChannel()
    assert image.width() >= 256
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() > 200


@pytest.mark.parametrize('theme_id', ['blossom', 'midnight', 'terminal'])
def test_drag_highlight_clears_on_leave_and_drop_without_changing_the_file(qtbot, tmp_path, theme_id):
    field = FileField('test_drop')
    qtbot.addWidget(field)
    field.setStyleSheet(build_stylesheet(theme_id))
    field.resize(450, 80)
    field.show()
    source = tmp_path / 'unchanged.txt'
    source.write_bytes(b'Original file stays unchanged')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    def enter():
        event = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(field, event)
        assert event.isAccepted()
    initial_geometry = field.edit.geometry()
    enter()
    assert field.edit.property('dragActive') is True
    assert field.edit.text() == ''
    assert field.edit.geometry() == initial_geometry
    QApplication.sendEvent(field, QDragLeaveEvent())
    assert field.edit.property('dragActive') is False
    enter()
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(field, drop)
    assert drop.isAccepted()
    assert field.edit.property('dragActive') is False
    assert Path(field.edit.text()) == source
    assert source.read_bytes() == b'Original file stays unchanged'


def test_result_detail_motion_finishes_and_reduced_motion_stops_it(qtbot):
    accent = FruitAccent(celebrate=True)
    qtbot.addWidget(accent)
    accent.set_theme(get_theme('blossom'))
    accent.show()
    assert accent._arrival.state() == QAbstractAnimation.State.Running
    qtbot.waitUntil(lambda: accent._arrival.state() == QAbstractAnimation.State.Stopped)
    assert accent._scale == 1
    accent.hide()
    accent.show()
    accent.set_reduce_motion(True)
    assert accent._arrival.state() == QAbstractAnimation.State.Stopped
    assert accent._scale == 1
    accent.hide()
    accent.show()
    assert accent._arrival.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize('possible', [Qt.DropAction.MoveAction,
                                    Qt.DropAction.CopyAction | Qt.DropAction.MoveAction])
def test_drop_never_acknowledges_moving_the_original(qtbot, tmp_path, possible):
    field = FileField('reference_only')
    qtbot.addWidget(field)
    field.show()
    source = tmp_path / 'keep-this.txt'
    source.write_bytes(b'Keep this source')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    drag = QDragEnterEvent(QPoint(10, 10), possible, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    QApplication.sendEvent(field, drag)
    if possible == Qt.DropAction.MoveAction:
        assert not drag.isAccepted()
        assert not field.edit.property('dragActive')
        assert field.edit.text() == ''
    else:
        assert drag.isAccepted() and drag.dropAction() == Qt.DropAction.CopyAction
        drop = QDropEvent(QPointF(10, 10), possible, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        QApplication.sendEvent(field, drop)
        assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
        assert Path(field.edit.text()) == source
    assert source.read_bytes() == b'Keep this source'


def test_empty_preview_art_changes_with_theme_but_selected_image_is_preserved(qtbot, tmp_path):
    preview = ImagePreview()
    qtbot.addWidget(preview)
    preview.resize(155, 112)
    preview.show()
    drawings = []
    for theme_id in ('blossom', 'midnight', 'terminal'):
        preview.set_theme(get_theme(theme_id))
        drawings.append(preview.grab().toImage())
    assert drawings[0] != drawings[1] != drawings[2]
    source = tmp_path / 'synthetic-cover.png'
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(source))
    assert preview.load_path(str(source)) == (80, 40)
    pixels = preview._image.toImage()
    for theme_id in ('blossom', 'midnight', 'terminal'):
        preview.set_theme(get_theme(theme_id))
        assert preview.state == ''
        assert preview._image.toImage() == pixels
