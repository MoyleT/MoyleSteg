"""Actual worker progress and cooperative cancellation do not publish output."""
from moyle_steg.worker import JobThread
from moyle_steg.service import OperationRequest


def test_cancel_before_start_is_distinct_from_failure_and_releases_request(qtbot, tmp_path):
    output = tmp_path / 'never.stegkey'
    job = JobThread(OperationRequest(operation='keygen', output_path=str(output)))
    canceled, errors, results = [], [], []
    job.cancelled.connect(lambda: canceled.append(True))
    job.failed.connect(errors.append)
    job.succeeded.connect(results.append)
    job.request_cancel()
    with qtbot.waitSignal(job.finished, timeout=10000):
        job.start()
    qtbot.waitUntil(lambda: bool(canceled))
    assert not errors and not results and not output.exists()
    assert job.request is None


def test_cancel_at_real_compression_progress_does_not_write(qtbot, tmp_path):
    class CancelAtCompression(JobThread):
        def _report_progress(self, stage, completed, total):
            super()._report_progress(stage, completed, total)
            if stage == 'compress':
                self.request_cancel()
    source = tmp_path / 'private.txt'
    source.write_bytes(b'cancellable payload' * 10000)
    output = tmp_path / 'never.saes'
    job = CancelAtCompression(OperationRequest(operation='encrypt', input_path=str(source), output_path=str(output),
        password='test worker credential', password_confirm='test worker credential'))
    events, canceled, errors = [], [], []
    job.progress.connect(lambda stage, done, total: events.append((stage, done, total)))
    job.cancelled.connect(lambda: canceled.append(True))
    job.failed.connect(errors.append)
    with qtbot.waitSignal(job.finished, timeout=15000):
        job.start()
    qtbot.waitUntil(lambda: bool(canceled))
    assert any(stage == 'read' and total == source.stat().st_size for stage, done, total in events)
    assert any(stage == 'compress' for stage, done, total in events)
    assert not errors and not output.exists()
    assert job.request is None
