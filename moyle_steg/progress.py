"""Small themed progress textures, driven only by real QProgressBar values.

The task owner explicitly starts and stops animation. Paint frames never write
values or emit fabricated progress, and unknown totals use unanchored packets.
"""
import math

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QProgressBar

from .theme import Theme, get_theme


def _mix(first, second, amount):
    a, b = QColor(first), QColor(second)
    return QColor(*(round(x * (1 - amount) + y * amount)
                    for x, y in zip(a.getRgb()[:3], b.getRgb()[:3])))


class ThemedProgressBar(QProgressBar):
    """Juice, data and meteor textures within a normal accessible progress bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme(None)
        self._reduce_motion = False
        self._running = False
        self._phase = 0.0
        self._observed_window = None
        self._frame_clock = QElapsedTimer()
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(40)
        self._animation_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._animation_timer.timeout.connect(self._advance_frame)
        self.valueChanged.connect(self._sync_animation)

    def set_appearance(self, theme, reduce_motion=False):
        self._theme = theme if isinstance(theme, Theme) else get_theme(theme)
        self._reduce_motion = bool(reduce_motion)
        self._phase = 0.0
        self._sync_animation()
        self.update()

    def set_running(self, running):
        self._running = bool(running)
        self._sync_animation()
        self.update()

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self._sync_animation()

    def setMinimum(self, minimum):
        super().setMinimum(minimum)
        self._sync_animation()

    def setMaximum(self, maximum):
        super().setMaximum(maximum)
        self._sync_animation()

    def reset(self):
        super().reset()
        self._sync_animation()

    def _indeterminate(self):
        return self.minimum() == self.maximum() == 0

    def _fraction(self):
        low, high, value = self.minimum(), self.maximum(), self.value()
        if value < low:
            return 0.0
        if high == low:
            return 1.0
        return max(0.0, min(1.0, (value - low) / (high - low)))

    def _should_animate(self):
        return (self._running and not self._reduce_motion and self.isVisible()
                and self.isEnabled() and not self.window().isMinimized()
                and (self._indeterminate() or 0 < self._fraction() < 1))

    def _sync_animation(self, *unused):
        if self._should_animate():
            if not self._animation_timer.isActive():
                self._frame_clock.start()
                self._animation_timer.start()
        else:
            self._animation_timer.stop()
            self._frame_clock.invalidate()

    def _advance_frame(self):
        if not self._should_animate():
            self._sync_animation()
            return
        seconds = min(self._frame_clock.restart() / 1000, .2)
        self._phase = (self._phase + seconds * .22) % 1
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        owner = self.window()
        if owner is not self and owner is not self._observed_window:
            if self._observed_window is not None:
                self._observed_window.removeEventFilter(self)
            self._observed_window = owner
            owner.installEventFilter(self)
        self._sync_animation()

    def hideEvent(self, event):
        self._animation_timer.stop()
        self._frame_clock.invalidate()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.WindowStateChange):
            self._sync_animation()

    def eventFilter(self, watched, event):
        if watched is self._observed_window and event.type() == QEvent.Type.WindowStateChange:
            self._sync_animation()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.save()
        vertical = self.orientation() == Qt.Orientation.Vertical
        width, height = float(self.width()), float(self.height())
        if vertical:
            painter.translate(0, height)
            painter.rotate(-90)
            width, height = height, width
        reversed_fill = self.invertedAppearance() ^ (
            not vertical and self.layoutDirection() == Qt.LayoutDirection.RightToLeft)
        if reversed_fill:
            painter.translate(width, 0)
            painter.scale(-1, 1)
        rect = QRectF(0, 0, width, height)
        radius = min(height / 2, 2 if self._theme.id == 'terminal' else 8)
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        painter.fillPath(track, QColor(self._theme.surface_alt))
        painter.setClipPath(track)

        if self._indeterminate():
            # Detached fixed-length textures convey an unknown total. Midnight
            # uses one complete meteor; the other themes use two gentle packets.
            # Neither creates an expanding edge that suggests a percentage.
            meteor = self._theme.id == 'midnight'
            length = max(48.0, width * .32) if meteor else max(24.0, width * .20)
            offsets = (.52,) if meteor else (.23, .73)
            intervals = [QRectF(((self._phase + offset) % 1) * (width + length) - length,
                                0, length, height) for offset in offsets]
        else:
            intervals = [QRectF(0, 0, width * self._fraction(), height)]

        for interval in intervals:
            if interval.width() <= 0:
                continue
            painter.save()
            if self._theme.id != 'midnight':
                painter.setClipRect(interval, Qt.ClipOperation.IntersectClip)
            # Only the faint meteor halo can pass the value edge. The tail
            # geometry and bright crystal stay behind it; a
            # local rectangular clip would give the glow an artificial seam.
            if self._theme.id == 'blossom':
                self._paint_juice(painter, rect)
            elif self._theme.id == 'terminal':
                self._paint_data(painter, rect)
            else:
                self._paint_meteors(painter, rect, interval)
            painter.restore()
        painter.restore()
        if self.isTextVisible() and self.text():
            painter.setPen(QColor(self._theme.text))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())

    def _paint_juice(self, painter, rect):
        width, height = rect.width(), rect.height()
        painter.fillRect(rect, _mix(self._theme.accent, self._theme.surface, .42))
        for shift, top, tint in ((0, .25, .65), (1.8, .55, .18)):
            wave = QPainterPath(QPointF(-2, height))
            for x in range(-2, math.ceil(width) + 3, 3):
                y = height * (top + .09 * math.sin(x / 29 + self._phase * math.tau * 2 + shift))
                wave.lineTo(x, y)
            wave.lineTo(width + 2, height)
            wave.closeSubpath()
            painter.fillPath(wave, _mix(self._theme.accent, self._theme.surface, tint))
        bubble = QColor(self._theme.on_accent)
        bubble.setAlpha(150)
        painter.setPen(QPen(bubble, .8))
        bubble_fill = QColor(bubble)
        bubble_fill.setAlpha(38)
        painter.setBrush(bubble_fill)
        for offset in (.17, .45, .74):
            x = ((offset + self._phase) % 1) * width
            y = height * (.38 + .12 * math.sin(self._phase * math.tau + offset * 9))
            r = max(.55, min(1.8, height * .075))
            painter.drawEllipse(QPointF(x, y), r, r)

    def _paint_meteors(self, painter, rect, interval):
        """The completed span is the tail of one star at the real value's edge."""
        height = rect.height()
        radius = min(4.4, height * .30, interval.width() / 2)
        head_x, middle = interval.right() - radius, height / 2
        start = interval.left()
        length = max(0.0, head_x - start)
        half_width = min(height * .21, 3.4)
        pulse = .5 + .5 * math.sin(self._phase * math.tau * 2)

        # A tapering silhouette replaces the filled rectangular background.
        # Only tint and the narrow inner wake breathe; the star's coordinates
        # are derived entirely from interval, hence from the real task value.
        tail = QPainterPath(QPointF(start, middle))
        tail.cubicTo(start + length * .32, middle - .25,
                     head_x - length * .23, middle - half_width * .75,
                     head_x, middle - half_width)
        tail.lineTo(head_x, middle + half_width)
        tail.cubicTo(head_x - length * .23, middle + half_width * .75,
                     start + length * .32, middle + .25, start, middle)
        tail.closeSubpath()
        gradient = QLinearGradient(start, middle, max(start + 1, head_x), middle)
        for position, color, alpha in ((0, '#6577DF', 0), (.15, '#6577DF', 45),
                                       (.65, self._theme.accent, 145 + round(pulse * 20)),
                                       (1, self._theme.accent, 235)):
            tint = QColor(color)
            tint.setAlpha(alpha)
            gradient.setColorAt(position, tint)
        painter.fillPath(tail, gradient)

        wake = QPainterPath(QPointF(start + length * .28, middle))
        wake.cubicTo(start + length * .60, middle + math.sin(self._phase * math.tau) * .4,
                     head_x - length * .14, middle, head_x, middle)
        painter.setPen(QPen(gradient, .8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(wake)

        halo_radius = min(height * .45, radius * 1.55)
        halo = QRadialGradient(QPointF(head_x, middle), max(.1, halo_radius))
        halo_color = QColor(self._theme.accent)
        halo_color.setAlpha(125 + round(pulse * 35))
        halo.setColorAt(0, halo_color)
        halo_color.setAlpha(0)
        halo.setColorAt(1, halo_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(head_x, middle), halo_radius, halo_radius)

        self._paint_crystal(painter, head_x, middle, radius)

    def _paint_crystal(self, painter, head_x, middle, radius):
        # A shaped white-hot crystal and asymmetric facets avoid a ball-shaped
        # slider thumb. Its leading point stays exactly at the measured edge.
        core = QPainterPath(QPointF(head_x + radius, middle))
        core.cubicTo(head_x + radius*.45, middle - radius*.40,
                     head_x + radius*.06, middle - radius*1.05,
                     head_x - radius*.33, middle - radius*.92)
        core.cubicTo(head_x - radius*.92, middle - radius*.66,
                     head_x - radius*.99, middle - radius*.15,
                     head_x - radius*.76, middle + radius*.12)
        core.cubicTo(head_x - radius*.99, middle + radius*.61,
                     head_x - radius*.20, middle + radius*1.03,
                     head_x + radius*.27, middle + radius*.66)
        core.closeSubpath()
        light = QRadialGradient(QPointF(head_x + radius*.08, middle - radius*.15), max(.1, radius*1.5))
        light.setColorAt(0, QColor('#FFFFFF'))
        light.setColorAt(.68, QColor('#F5EAFF'))
        light.setColorAt(1, QColor('#C8A7FF'))
        painter.fillPath(core, light)
        facet = QPainterPath(QPointF(head_x - radius*.57, middle - radius*.36))
        facet.lineTo(head_x + radius*.55, middle)
        facet.lineTo(head_x - radius*.28, middle + radius*.59)
        facet.closeSubpath()
        painter.fillPath(facet, QColor('#FFFFFF'))

    def _paint_data(self, painter, rect):
        width, height = rect.width(), rect.height()
        painter.fillRect(rect, _mix(self._theme.surface_alt, self._theme.accent, .19))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        cell = max(.7, min(1.4, height / 10))
        spacing = cell * 6
        offset = math.floor(self._phase * spacing * 8)
        digits = ('111101101101111', '010110010010111')
        for index in range(-2, math.ceil(width / spacing) + 2):
            x = index * spacing + offset % spacing
            tone = QColor(self._theme.accent)
            tone.setAlpha(110 + (index % 3) * 60)
            painter.setBrush(tone)
            painter.setPen(Qt.PenStyle.NoPen)
            for bit, lit in enumerate(digits[(index + offset // max(1, round(spacing))) % 2]):
                if lit == '1':
                    painter.drawRect(QRectF(x + (bit % 3) * cell,
                                            (height - cell * 5) / 2 + (bit // 3) * cell,
                                            cell, cell))


# Compatibility with the original focused integration name.
JuiceProgressBar = ThemedProgressBar
