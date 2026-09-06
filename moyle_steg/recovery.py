"""Per-task recovery budgets with a background, read-only disk estimate."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, Signal, Slot, QRunnable, QThreadPool
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QCheckBox

from .i18n import tr
from .service import (DEFAULT_MAX_PIXELS, DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_CONTAINER_BYTES,
                      probe_recovery_resources, friendly_error)


class _ResourceSignals(QObject):
    finished = Signal(object, object, object)


class _ResourceProbe(QRunnable):
    """A pool-owned task may outlive its panel without owning any widgets."""
    def __init__(self, token):
        super().__init__()
        self.token = token
        self.signals = _ResourceSignals()

    def run(self):
        _, path, operation = self.token
        resources = error = None
        try:
            resources = probe_recovery_resources(path, operation=operation)
        except Exception as exc:
            error = exc
        self.signals.finished.emit(self.token, resources, error)


def size_text(value):
    number = float(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if number < 1024 or unit == 'TiB':
            return f'{number:.1f} {unit}'
        number /= 1024


class RecoveryBudgetPanel(QWidget):
    """Higher limits require acknowledgement for this input and this run only."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.language = 'zh_CN'
        self._path = ''
        self._operation = 'verify'
        self._resources = None
        self._resource_error = None
        self._resource_generation = 0
        self._resource_task = None
        self._probe_requested = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.resources_label = QLabel()
        self.resources_label.setWordWrap(True)
        self.resources_label.setTextFormat(Qt.TextFormat.PlainText)
        self.resources_label.setProperty('role', 'muted')
        layout.addWidget(self.resources_label)
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setObjectName('recovery_budget_toggle')
        layout.addWidget(self.toggle)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self._labels = []
        self.pixels = self._spin(body, 'budget_pixels', 1, 100_000_000, DEFAULT_MAX_PIXELS)
        self.payload = self._spin(body, 'budget_payload', 1, 1024, DEFAULT_MAX_FILE_BYTES // 1024**2)
        self.container = self._spin(body, 'budget_container', 1, 4096, DEFAULT_MAX_CONTAINER_BYTES // 1024**2)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setProperty('role', 'muted')
        body.addWidget(self.warning)
        self.memory_label = QLabel()
        self.memory_label.setWordWrap(True)
        self.memory_label.setProperty('role', 'muted')
        body.addWidget(self.memory_label)
        self.confirm = QCheckBox()
        self.confirm.setObjectName('recovery_budget_confirm')
        body.addWidget(self.confirm)
        layout.addWidget(self.body)
        self.body.hide()
        self.toggle.toggled.connect(self.body.setVisible)
        for spin in (self.pixels, self.payload, self.container):
            spin.valueChanged.connect(self._changed)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh_resources)
        self.set_language('zh_CN')

    def _spin(self, layout, key, minimum, maximum, value):
        row = QHBoxLayout()
        label = QLabel()
        label.setProperty('role', 'fieldLabel')
        label.setWordWrap(True)
        spin = QSpinBox()
        spin.setObjectName(key)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setGroupSeparatorShown(True)
        spin.setMinimumWidth(125)
        label.setBuddy(spin)
        self._labels.append((label, spin, key))
        row.addWidget(label, 1)
        row.addWidget(spin)
        layout.addLayout(row)
        return spin

    def limits(self):
        return dict(max_pixels=self.pixels.value(), max_file_bytes=self.payload.value() * 1024**2,
                    max_container_bytes=self.container.value() * 1024**2)

    def elevated(self):
        limits = self.limits()
        return (limits['max_pixels'] > DEFAULT_MAX_PIXELS or limits['max_file_bytes'] > DEFAULT_MAX_FILE_BYTES
                or limits['max_container_bytes'] > DEFAULT_MAX_CONTAINER_BYTES)

    def _changed(self):
        self.confirm.setChecked(False)
        self._render()

    def set_input(self, path, operation='verify'):
        path = str(Path(path).expanduser().absolute()) if path else ''
        if path != self._path or operation != self._operation:
            self.confirm.setChecked(False)
        self._path, self._operation = path, operation
        self._resource_generation += 1
        self._resources = self._resource_error = None
        self._probe_requested = bool(path)
        self._render()
        self._timer.start()

    def refresh_resources(self):
        """Schedule fresh metadata I/O; never perform it on the GUI thread."""
        self._timer.stop()
        self._resource_generation += 1
        self._resources = self._resource_error = None
        self._probe_requested = bool(self._path)
        self._render()
        self._start_resource_probe()

    def _start_resource_probe(self):
        if self._resource_task is not None or not self._probe_requested:
            return
        self._probe_requested = False
        token = self._resource_generation, self._path, self._operation
        self._resource_task = task = _ResourceProbe(token)
        task.signals.finished.connect(self._resource_finished)
        QThreadPool.globalInstance().start(task)

    @Slot(object, object, object)
    def _resource_finished(self, token, resources, error):
        self._resource_task = None
        if token == (self._resource_generation, self._path, self._operation):
            self._resources, self._resource_error = resources, error
            self._render()
        if self._probe_requested and not self._timer.isActive():
            self._start_resource_probe()

    def display_resources(self, info, path, operation):
        """Display the active worker's snapshot, superseding older previews."""
        self._timer.stop()
        self._resource_generation += 1
        self._probe_requested = False
        self._path = str(Path(path).expanduser().absolute()) if path else ''
        self._operation = operation
        self._resources, self._resource_error = info, None
        self._render()

    def validate(self):
        if self.elevated() and not self.confirm.isChecked():
            self.toggle.setChecked(True)
            return 'budget_confirm_required'
        return None

    def set_language(self, language):
        self.language = language
        self.toggle.setText(tr('budget_advanced', language))
        for label, spin, key in self._labels:
            label.setText(tr(key, language))
            spin.setAccessibleName(tr(key, language))
        self.warning.setText(tr('budget_warning', language))
        self.confirm.setText(tr('budget_confirm', language))
        self._render()

    def _render(self):
        self.confirm.setVisible(self.elevated())
        reference = self.pixels.value() * 12 + self.payload.value() * 1024**2 * 3
        self.memory_label.setText(tr('budget_memory', self.language, memory=size_text(reference)))
        if self._resources is not None:
            info = self._resources
            key = 'budget_space' if self._operation in ('verify', 'inspect') else 'budget_input_size'
            self.resources_label.setText(tr(key, self.language, size=size_text(info.input_size),
                required=size_text(info.temporary_required), free=size_text(info.temporary_free)))
        elif self._resource_error is not None:
            self.resources_label.setText(friendly_error(self._resource_error, self.language))
        else:
            self.resources_label.setText(tr('budget_choose_input', self.language))
