"""Native reusable widgets; filesystem processing stays in the service worker."""
from pathlib import Path
import math

from PySide6.QtCore import Qt, Signal, QSize, QRectF, QPointF, QVariantAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QImageReader, QImageIOHandler, QPixmap, QIcon, QPainterPath, QTextOption
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QStackedLayout, QTextBrowser, QSizePolicy


class WrapTextLabel(QTextBrowser):
    """Selectable plain text that wraps long filenames and hashes without loss."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.document().documentLayout().documentSizeChanged.connect(self.updateGeometry)

    def setText(self, text):
        # Never interpret authenticated filenames as HTML or insert wrap markers
        # into text that the user might select and copy.
        self.setPlainText(text)
        self.updateGeometry()

    def text(self):
        return self.toPlainText()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        # Measure independently: layout negotiation must not change the live
        # document width and therefore the text currently being displayed.
        document = self.document().clone()
        document.setTextWidth(max(1, width - 2))
        height = math.ceil(document.documentLayout().documentSize().height()) + 2
        return height

    def sizeHint(self):
        return QSize(320, self.heightForWidth(320))

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height() + 2)


class _PageLayout(QStackedLayout):
    """Hidden long pages must not add a phantom scrollbar to a short form."""
    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSize(self):
        page = self.currentWidget()
        return page.minimumSizeHint().expandedTo(page.minimumSize()) if page is not None else super().minimumSize()

    def hasHeightForWidth(self):
        page = self.currentWidget()
        return page.hasHeightForWidth() if page is not None else False

    def heightForWidth(self, width):
        page = self.currentWidget()
        return page.heightForWidth(width) if page is not None else -1


class PageStack(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages = _PageLayout(self)
        self._pages.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, widget):
        return self._pages.addWidget(widget)

    def setCurrentWidget(self, widget):
        self._pages.setCurrentWidget(widget)
        self._pages.invalidate()
        self.updateGeometry()

    def currentWidget(self):
        return self._pages.currentWidget()


_FRUIT_PIXMAPS = {}
_ASSETS = Path(__file__).resolve().parent.parent / 'assets'


def draw_fruit(painter, rect, kind='strawberry'):
    """Render the packaged transparent stickers at native display resolution."""
    if kind not in ('strawberry', 'cherry'):
        raise ValueError('Unknown fruit sticker')
    if kind not in _FRUIT_PIXMAPS:
        sticker = QPixmap(str(_ASSETS / f'{kind}-sticker.png'))
        if sticker.isNull():
            raise RuntimeError(f'Missing packaged {kind} sticker')
        _FRUIT_PIXMAPS[kind] = sticker
    sticker = _FRUIT_PIXMAPS[kind]
    scale = min(rect.width() / sticker.width(), rect.height() / sticker.height())
    width, height = sticker.width() * scale, sticker.height() * scale
    target = QRectF(rect.center().x() - width / 2, rect.center().y() - height / 2, width, height)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(target, sticker, QRectF(sticker.rect()))
    painter.restore()


class FruitAccent(QWidget):
    """Small themed illustration in a fixed slot, optionally welcoming a result."""
    def __init__(self, parent=None, celebrate=False):
        super().__init__(parent)
        self.setFixedSize(78, 28)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.theme = None
        self.celebrate = celebrate
        self.reduce_motion = False
        self._scale = 1.0
        self._arrival = QVariantAnimation(self)
        self._arrival.setDuration(260)
        self._arrival.setEasingCurve(QEasingCurve.Type.OutBack)
        self._arrival.valueChanged.connect(self._set_scale)

    def _set_scale(self, scale):
        self._scale = float(scale)
        self.update()

    def set_reduce_motion(self, reduce):
        self.reduce_motion = bool(reduce)
        if self.reduce_motion:
            self._arrival.stop()
            self._set_scale(1)

    def showEvent(self, event):
        super().showEvent(event)
        if self.celebrate and not self.reduce_motion:
            self._arrival.setStartValue(0.72)
            self._arrival.setEndValue(1.0)
            self._arrival.start()

    def hideEvent(self, event):
        self._arrival.stop()
        self._set_scale(1)
        super().hideEvent(event)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        if self.theme is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(39, 14)
        painter.scale(self._scale, self._scale)
        painter.translate(-39, -14)
        if self.theme.id == 'blossom':
            draw_fruit(painter, QRectF(4, 0, 28, 28))
            draw_fruit(painter, QRectF(43, 0, 29, 28), 'cherry')
            painter.setPen(QPen(QColor('#D786A1'), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(37, 7, 37, 13)
            painter.drawLine(34, 10, 40, 10)
        elif self.theme.id == 'midnight':
            painter.setPen(QPen(QColor(self.theme.border), 1))
            painter.drawLine(QPointF(9, 21), QPointF(29, 9))
            painter.drawLine(QPointF(29, 9), QPointF(52, 18))
            painter.drawLine(QPointF(52, 18), QPointF(70, 5))
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y, radius in ((9, 21, 1.5), (29, 9, 2.5), (52, 18, 2), (70, 5, 1.5)):
                painter.setBrush(QColor(self.theme.accent))
                painter.drawEllipse(QPointF(x, y), radius, radius)
        else:
            painter.setPen(QPen(QColor(self.theme.accent), 1.4))
            painter.drawLine(8, 8, 14, 14)
            painter.drawLine(14, 14, 8, 20)
            painter.drawLine(18, 20, 27, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            for x, height in ((39, 5), (45, 10), (51, 7), (57, 15), (63, 11), (69, 18)):
                painter.fillRect(QRectF(x, 23 - height, 3, height), QColor(self.theme.accent))


class ActionButton(QPushButton):
    """Theme-specific hover feedback painted inside the existing button padding."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = None
        self.reduce_motion = False
        self._hover_mix = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_mix)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_hover_mix(self, value):
        self._hover_mix = float(value)
        self.update()

    def set_appearance(self, theme, reduce_motion=False):
        self.theme = theme
        self.reduce_motion = bool(reduce_motion)
        self._hover_animation.stop()
        self._set_hover_mix(1 if self.underMouse() and self.isEnabled() else 0)

    def _animate_hover(self, target):
        self._hover_animation.stop()
        if self.reduce_motion or (self.theme and self.theme.id == 'terminal'):
            self._set_hover_mix(target)
        elif self._hover_mix != target:
            self._hover_animation.setStartValue(self._hover_mix)
            self._hover_animation.setEndValue(float(target))
            self._hover_animation.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.isEnabled():
            self._animate_hover(1)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate_hover(0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._hover_animation.stop()
            self._set_hover_mix(0)

    def hideEvent(self, event):
        self._hover_animation.stop()
        self._set_hover_mix(0)
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.theme is None or not self.isEnabled() or self._hover_mix <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._hover_mix)
        painter.translate(self.width() - 10, self.height() / 2)
        ink = QColor(self.theme.on_accent)
        painter.setPen(QPen(ink, 1.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if self.theme.id == 'blossom':
            painter.rotate(-12 * (1 - self._hover_mix))
            heart = QPainterPath(QPointF(0, 3.5))
            heart.cubicTo(-8, -1, -3, -7, 0, -3)
            heart.cubicTo(3, -7, 8, -1, 0, 3.5)
            painter.fillPath(heart, ink)
        elif self.theme.id == 'midnight':
            star = QPainterPath(QPointF(0, -4))
            for point in ((1.2, -1.2), (4, 0), (1.2, 1.2), (0, 4), (-1.2, 1.2), (-4, 0), (-1.2, -1.2), (0, -4)):
                star.lineTo(*point)
            painter.fillPath(star, ink)
        else:
            painter.drawLine(QPointF(-2, -3), QPointF(1, 0))
            painter.drawLine(QPointF(1, 0), QPointF(-2, 3))


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 40)
        self._accent = '#B9A6FF'

    def set_theme(self, theme):
        self._accent = theme.accent
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self._accent), 2.4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(QPointF(4, 29))
        for point in ((4, 12), (16, 22), (28, 12), (28, 29)):
            path.lineTo(*point)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._accent))
        painter.drawEllipse(QPointF(16, 10), 2.5, 2.5)


def line_icon(name, color, selected=None, theme_id=None):
    """Stable task glyphs and theme emblems, rasterized at 3x for high-DPI Qt."""
    icon = QIcon()
    for state, tint in ((QIcon.State.Off, color), (QIcon.State.On, selected or color)):
        pixmap = QPixmap(72, 72)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(3, 3)
        painter.setPen(QPen(QColor(tint), 1.7, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        def path(points):
            shape = QPainterPath(QPointF(*points[0]))
            for point in points[1:]:
                shape.lineTo(*point)
            painter.drawPath(shape)
        if name == 'hide':
            painter.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
            painter.drawEllipse(QPointF(8, 9), 1.3, 1.3)
            path([(4, 17), (9, 12), (13, 16), (17, 11), (20, 14)])
        elif name == 'extract':
            path([(5, 9), (5, 20), (19, 20), (19, 9)])
            path([(12, 15), (12, 3)])
            path([(8, 7), (12, 3), (16, 7)])
        elif name == 'crypt':
            painter.drawRoundedRect(QRectF(5, 10, 14, 11), 2, 2)
            painter.drawArc(QRectF(8, 2, 8, 13), 0, 180 * 16)
            painter.drawLine(12, 14, 12, 17)
        elif name == 'verify':
            path([(12, 2), (20, 5), (19, 14), (16, 19), (12, 22), (8, 19), (5, 14), (4, 5), (12, 2)])
            path([(8, 11), (11, 14), (16, 9)])
        elif name == 'keygen':
            painter.drawEllipse(QRectF(3, 3, 9, 9))
            path([(11, 11), (20, 20), (22, 18), (19, 15), (17, 17)])
        elif name == 'guide':
            painter.drawRoundedRect(QRectF(5, 3, 15, 18), 2, 2)
            painter.drawLine(9, 3, 9, 21)
            painter.drawLine(12, 8, 16, 8)
            painter.drawLine(12, 12, 16, 12)
        elif name == 'arrow':
            path([(4, 12), (20, 12)])
            path([(15, 7), (20, 12), (15, 17)])
        elif name in ('midnight', 'blossom', 'terminal'):
            if name == 'midnight':
                crescent = QPainterPath()
                crescent.addEllipse(QRectF(4, 3, 17, 18))
                cut = QPainterPath()
                cut.addEllipse(QRectF(10, 0, 15, 16))
                painter.fillPath(crescent.subtracted(cut), QColor(tint))
            elif name == 'blossom':
                draw_fruit(painter, QRectF(1, 1, 21, 22), 'cherry')
            else:
                path([(4, 6), (10, 12), (4, 18)])
                painter.drawLine(13, 18, 21, 18)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class FileField(QWidget):
    browse_requested = Signal()
    path_changed = Signal(str)

    def __init__(self, object_name, save=False, parent=None):
        super().__init__(parent)
        self.save = save
        self.directory = False
        self.setAcceptDrops(not save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.label = QLabel()
        self.label.setProperty('role', 'fieldLabel')
        layout.addWidget(self.label)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit()
        # Let FileField handle local URLs, instead of inserting file:/// text.
        self.edit.setAcceptDrops(False)
        self.edit.setObjectName(object_name)
        self.label.setBuddy(self.edit)
        self.edit.setClearButtonEnabled(True)
        self.browse = QPushButton()
        self.browse.setObjectName(object_name + '_browse')
        self.browse.setMinimumWidth(82)
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.edit.textChanged.connect(self.path_changed)
        self.browse.clicked.connect(self.browse_requested)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        accepted = (bool(event.possibleActions() & Qt.DropAction.CopyAction)
                    and not self.save and self.isEnabled() and len(urls) == 1
                    and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_file())
        self._set_drag_active(accepted)
        if accepted:
            # The form references the original; never acknowledge a move that
            # could tell the drag source to remove its file.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def _set_drag_active(self, active):
        self.edit.setProperty('dragActive', bool(active))
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        self.edit.update()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        if (bool(event.possibleActions() & Qt.DropAction.CopyAction)
                and not self.save and self.isEnabled() and len(urls) == 1
                and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_file()):
            self.edit.setText(urls[0].toLocalFile())
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()


class Card(QFrame):
    def __init__(self, parent=None, kind='section'):
        super().__init__(parent)
        self.setObjectName('card')
        self.setProperty('kind', kind)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(10)


class ImagePreview(QLabel):
    """Bounded decode: huge images get header metadata but no synchronous preview."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('imagePreview')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(112)
        self.setMaximumHeight(140)
        self.setWordWrap(True)
        self._image = None
        self.state = 'preview_empty'
        self._theme = None

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def paintEvent(self, event):
        if self.state != 'preview_empty' or self._theme is None:
            return super().paintEvent(event)
        # A quiet pixel-window illustration locates the preview without a large
        # decorative image. Actual user images retain the existing decode path.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self._theme.border), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(self._theme.preview_bg))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        if self._theme.id == 'blossom':
            draw_fruit(painter, QRectF(self.width() / 2 - 37, 8, 40, 42))
            draw_fruit(painter, QRectF(self.width() / 2 + 5, 14, 33, 34), 'cherry')
        elif self._theme.id == 'midnight':
            color = QColor(self._theme.accent)
            painter.setPen(QPen(QColor(self._theme.border), 1))
            center = self.width() / 2
            painter.drawEllipse(QRectF(center - 36, 11, 72, 35))
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y, radius in ((-31, 18, 1.5), (32, 35, 2), (17, 9, 1), (-15, 45, 1)):
                painter.setBrush(color)
                painter.drawEllipse(QPointF(center + x, y), radius, radius)
            line_icon('midnight', self._theme.accent).paint(painter, int(center - 15), 15, 30, 30)
        else:
            center = self.width() / 2
            painter.setPen(QPen(QColor(self._theme.border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(center - 32, 10, 64, 38), 2, 2)
            painter.drawLine(QPointF(center - 32, 19), QPointF(center + 32, 19))
            line_icon('terminal', self._theme.accent).paint(painter, int(center - 12), 21, 24, 24)
        painter.setPen(QColor(self._theme.muted))
        painter.drawText(QRectF(8, 57, self.width() - 16, self.height() - 63),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.text())

    def load_path(self, path):
        self._image = None
        self.clear()
        self.state = 'preview_empty'
        if not path:
            return None
        reader = QImageReader(path)
        size = reader.size()
        if not size.isValid():
            self.state = 'preview_error'
            return None
        # EXIF quarter-turns transpose the displayed width and height. Query
        # only header metadata; the existing bounded decode policy is unchanged.
        quarter_turn = bool(reader.transformation().value & QImageIOHandler.Transformation.TransformationRotate90.value)
        dimensions = (size.height(), size.width()) if quarter_turn else (size.width(), size.height())
        if size.width() * size.height() > 16_000_000:
            self.state = 'preview_limited'
            return dimensions
        reader.setAutoTransform(True)
        reader.setScaledSize(size.scaled(QSize(480, 300), Qt.AspectRatioMode.KeepAspectRatio))
        loaded = reader.read()
        if loaded.isNull():
            self.state = 'preview_error'
        else:
            self._image = QPixmap.fromImage(loaded)
            self.state = ''
            self._scale()
        return dimensions

    def _scale(self):
        if self._image:
            self.setPixmap(self._image.scaled(self.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale()
