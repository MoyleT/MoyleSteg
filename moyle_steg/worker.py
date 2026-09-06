"""Run the synchronous engine outside Qt's interface thread."""
from threading import Event
from time import monotonic
from dataclasses import replace
from PySide6.QtCore import QThread, Signal
from png_steg_aes256 import OperationControl, OperationCancelled
from .service import OperationRequest, execute, friendly_error, probe_recovery_resources


class JobThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    # Python objects preserve large byte counters and None for unknown totals.
    progress = Signal(str, object, object)
    resource_ready = Signal(object)

    def __init__(self, request: OperationRequest, language='zh_CN', parent=None, *, resource_preview=False):
        super().__init__(parent)
        self.request = replace(request)
        self.language = language
        self.error_messages = {}
        self._cancel_event = Event()
        self._last_progress_time = 0.0
        self._last_stage = None
        self._resource_preview = resource_preview
        self._resource_ack = Event()

    def request_cancel(self):
        self._cancel_event.set()
        self._resource_ack.set()

    def acknowledge_resources(self):
        """The interface has displayed the estimate; execution may proceed."""
        self._resource_ack.set()

    def _report_progress(self, stage, completed, total):
        now = monotonic()
        if stage != self._last_stage or now - self._last_progress_time >= 0.05 or (total is not None and completed == total):
            self._last_progress_time = now
            self._last_stage = stage
            self.progress.emit(stage, completed, total)

    def run(self):
        try:
            request = replace(self.request)
            control = OperationControl(progress=self._report_progress, cancelled=self._cancel_event.is_set)
            control.check()
            if self._resource_preview and request.operation in {'extract', 'inspect', 'decrypt', 'verify'}:
                control.report('resources')
                resources = probe_recovery_resources(request.input_path, operation=request.operation)
                control.check()
                self.resource_ready.emit(resources)
                while not self._resource_ack.wait(0.05):
                    control.check()
                control.check()
            result = execute(request, control=control)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.error_messages = {
                language: friendly_error(error, language)
                for language in ('zh_CN', 'en_US')
            }
            self.failed.emit(self.error_messages.get(self.language, self.error_messages['zh_CN']))
        else:
            self.succeeded.emit(result)
        finally:
            self.request = None
