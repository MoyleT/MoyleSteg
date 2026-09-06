"""Adaptive layout in Qt logical pixels, independent of forms and presentation."""

from PySide6.QtCore import QEvent, QMargins, QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication, QBoxLayout, QLayout, QSizePolicy, QWidget


def bounded_client_geometry(available_geometry, requested_size, frame_margins=None,
                            *, margin=12, position=None):
    """Return a client rectangle whose *outer frame* fits availableGeometry().

    All arguments are logical Qt coordinates: do not multiply by screen DPR.
    With no position, center the outer frame; otherwise clamp the requested
    client position. Negative and nonzero screen origins are preserved.
    """
    available = QRect(available_geometry)
    requested = QSize(requested_size)
    frame = QMargins(frame_margins) if frame_margins is not None else QMargins()
    if available.isEmpty() or requested.isEmpty() or margin < 0:
        raise ValueError('Screen, requested size, and margin must be valid')
    if min(frame.left(), frame.top(), frame.right(), frame.bottom()) < 0:
        raise ValueError('Frame margins cannot be negative')
    # Retain the requested breathing room whenever the screen permits it.
    horizontal = min(margin, max(0, (available.width() - frame.left() - frame.right() - 1) // 2))
    vertical = min(margin, max(0, (available.height() - frame.top() - frame.bottom() - 1) // 2))
    inner = available.adjusted(horizontal, vertical, -horizontal, -vertical)
    maximum = QSize(inner.width() - frame.left() - frame.right(),
                    inner.height() - frame.top() - frame.bottom())
    if maximum.isEmpty():
        raise ValueError('The available screen is smaller than the window frame')
    size = requested.boundedTo(maximum)
    left, top = inner.left() + frame.left(), inner.top() + frame.top()
    right = inner.right() - frame.right() - size.width() + 1
    bottom = inner.bottom() - frame.bottom() - size.height() + 1
    if position is None:
        origin = QPoint(left + (right - left) // 2, top + (bottom - top) // 2)
    else:
        origin = QPoint(min(max(position.x(), left), right), min(max(position.y(), top), bottom))
    return QRect(origin, size)


def fit_window_to_screen(window, screen=None, *, available_geometry=None,
                         preferred_size=None, margin=12, center=True):
    """Apply available screen bounds after show, when native frame margins exist.

    Call from a deferred show handler or a screen-change handler. This does not
    alter monitor configuration, maximize the window, or apply a DPI multiplier.
    If its explicit minimum exceeds the available client area, that minimum is
    capped too; children must provide responsive layout or their own scrolling.
    """
    if available_geometry is None:
        selected = screen if screen is not None else window.screen()
        selected = selected if selected is not None else QApplication.primaryScreen()
        if selected is None:
            raise ValueError('No screen is available for the window')
        available_geometry = selected.availableGeometry()
    handle = window.windowHandle()
    if handle is not None:
        frame = handle.frameMargins()
    else:
        client, outer = window.geometry(), window.frameGeometry()
        frame = QMargins(max(0, client.left() - outer.left()), max(0, client.top() - outer.top()),
                         max(0, outer.right() - client.right()), max(0, outer.bottom() - client.bottom()))
    requested = QSize(preferred_size) if preferred_size is not None else window.size()
    requested = requested.expandedTo(window.minimumSize())
    target = bounded_client_geometry(
        available_geometry, requested, frame, margin=margin,
        position=None if center else window.geometry().topLeft())
    if window.minimumSize().boundedTo(target.size()) != window.minimumSize():
        window.setMinimumSize(window.minimumSize().boundedTo(target.size()))
    window.resize(target.size())
    # Use the explicit frame-position API. Unlike client positioning, this
    # also avoids offscreen QPA's origin clamp on negative screen coordinates.
    outer_position = target.topLeft() - QPoint(frame.left(), frame.top())
    if handle is not None:
        handle.setFramePosition(outer_position)
    else:
        window.move(outer_position)
    return target


class _ResponsiveBoxLayout(QBoxLayout):
    """Expose responsive height through the API QWidgetItem actually queries.

    Qt asks a child widget's *layout* for height-for-width when it has one.
    Defining it only on ResponsiveColumns leaves nonwrapping header layouts at
    -1, and leaves stacked rows using the old direction during parent planning.
    """

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.parentWidget().heightForWidth(width)

    def minimumHeightForWidth(self, width):
        return self.heightForWidth(width)


class ResponsiveColumns(QWidget):
    """Switch an existing QBoxLayout between columns and a vertical stack.

    addLayout wraps that same layout in a widget; it never copies its controls.
    The minimum width describes a single column, so the horizontal arrangement
    cannot stop its parent from shrinking far enough to reach the breakpoint.
    A height-for-width hint lets an enclosing QScrollArea expose stacked forms.
    """

    def __init__(self, parent=None, *, breakpoint=720, spacing=16):
        super().__init__(parent)
        if breakpoint < 1 or spacing < 0:
            raise ValueError('Breakpoint must be positive and spacing nonnegative')
        self.breakpoint = int(breakpoint)
        self.box = _ResponsiveBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)
        self.box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    @property
    def is_stacked(self):
        return self.box.direction() == QBoxLayout.Direction.TopToBottom

    def addWidget(self, widget, stretch=1):
        self.box.addWidget(widget, stretch)
        self._sync_direction()
        self.updateGeometry()

    def addLayout(self, layout, stretch=1):
        column = QWidget()
        column.setLayout(layout)
        self.addWidget(column, stretch)
        return column

    def _items(self):
        return [(self.box.itemAt(index), max(1, self.box.stretch(index)))
                for index in range(self.box.count()) if not self.box.itemAt(index).isEmpty()]

    def _stack_at(self, width):
        items = self._items()
        margins = self.box.contentsMargins()
        horizontal_minimum = (sum(item.minimumSize().width() for item, _ in items)
                              + max(0, len(items) - 1) * self.box.spacing()
                              + margins.left() + margins.right())
        return width < max(self.breakpoint, horizontal_minimum)

    def _sync_direction(self):
        direction = (QBoxLayout.Direction.TopToBottom if self._stack_at(self.width())
                     else QBoxLayout.Direction.LeftToRight)
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            self.updateGeometry()

    def resizeEvent(self, event):
        self._sync_direction()
        super().resizeEvent(event)

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, 'box'):
            # Translations, font metrics, and hidden credential rows can change
            # a column's minimum width without resizing the outer window.
            self._sync_direction()
        return handled

    def minimumSizeHint(self):
        items = self._items()
        margins = self.box.contentsMargins()
        return QSize(max((item.minimumSize().width() for item, _ in items), default=0)
                     + margins.left() + margins.right(),
                     max((item.minimumSize().height() for item, _ in items), default=0)
                     + margins.top() + margins.bottom())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        items = self._items()
        margins = self.box.contentsMargins()
        usable = max(1, width - margins.left() - margins.right())
        spacing = max(0, len(items) - 1) * self.box.spacing()
        if not items:
            return margins.top() + margins.bottom()

        def height(item, item_width):
            desired = item.heightForWidth(item_width) if item.hasHeightForWidth() else item.sizeHint().height()
            return max(item.minimumSize().height(), desired)

        if self._stack_at(width):
            content_height = sum(height(item, usable) for item, _ in items) + spacing
        else:
            # Resolve proportional widths with lower bounds, as QBoxLayout does
            # for these expanding columns. A wide minimum cannot starve a peer.
            remaining = max(1, usable - spacing)
            pending = list(range(len(items)))
            widths = [0] * len(items)
            while pending:
                total_stretch = sum(items[index][1] for index in pending)
                constrained = [index for index in pending
                               if remaining * items[index][1] / total_stretch < items[index][0].minimumSize().width()]
                if not constrained:
                    for index in pending[:-1]:
                        widths[index] = remaining * items[index][1] // total_stretch
                    widths[pending[-1]] = remaining - sum(widths[index] for index in pending[:-1])
                    break
                for index in constrained:
                    widths[index] = items[index][0].minimumSize().width()
                    remaining -= widths[index]
                    pending.remove(index)
            content_height = max(height(item, widths[index]) for index, (item, _) in enumerate(items))
        return content_height + margins.top() + margins.bottom()
