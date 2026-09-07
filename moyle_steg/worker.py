"""Run the synchronous engine outside Qt's interface thread."""
from threading import Event
from time import monotonic, sleep
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
        # Pixel/layout loops are Python-heavy. Merely emitting a queued signal
        # does not let the GUI's Python paint/event handlers acquire the GIL.
        # Yield at the core's bounded checkpoints; keep real progress unchanged.
        sleep(0.001)

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


class BundleJobThread(JobThread):
    """Publish from an authenticated session; credentials are never re-read."""
    def __init__(self, result, indices, directory, language='zh_CN', parent=None, *, whole_archive=False):
        super().__init__(OperationRequest(result.operation), language, parent)
        self.result = result
        self.indices = tuple(indices)
        self.directory = directory
        self.whole_archive = whole_archive

    def run(self):
        session = self.result.bundle
        error = None
        try:
            control = OperationControl(progress=self._report_progress, cancelled=self._cancel_event.is_set)
            if self.whole_archive:
                session.save_archive(self.directory, control=control)
            else:
                session.save(self.indices, self.directory, control=control)
        except OperationCancelled:
            error = 'cancelled'
        except Exception as exc:
            error = exc
        finally:
            # Publish each committed path even after a later failure/cancellation.
            title = 'bundle_partial' if error else 'bundle_saved'
            self.succeeded.emit(replace(self.result, title=title,
                       details={**self.result.details, 'saved_files': str(len(session.saved))}))
            if isinstance(error, Exception):
                self.error_messages = {lang: friendly_error(error, lang) for lang in ('zh_CN', 'en_US')}
                self.failed.emit(self.error_messages[self.language])
            self.request = None
