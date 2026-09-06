"""Background execution must report real results and recover after failures."""

from pathlib import Path

from PySide6.QtCore import QThread


def test_job_runs_in_background_and_emits_generated_file(qtbot, tmp_path):
    # A synchronous implementation or missing result signal would break this contract.
    from moyle_steg.worker import JobThread
    from moyle_steg.service import OperationRequest

    target = tmp_path / "worker.stegkey"
    job = JobThread(OperationRequest(operation="keygen", output_path=str(target)))
    results = []
    job.succeeded.connect(results.append)
    assert isinstance(job, QThread)
    with qtbot.waitSignal(job.finished, timeout=10000):
        job.start()
    qtbot.waitUntil(lambda: bool(results))
    assert Path(results[0].output_path) == target
    assert target.read_text().startswith("PNG-STEG-AES256-KEY-V1")
    assert job.request is None


def test_job_failure_emits_english_and_does_not_create_output(qtbot, tmp_path):
    # Errors must return to the interface, release credentials, and never signal success.
    from moyle_steg.worker import JobThread
    from moyle_steg.service import OperationRequest

    target = tmp_path / "never.saes"
    job = JobThread(
        OperationRequest(operation="encrypt", input_path=str(tmp_path / "missing"),
                         output_path=str(target), password="private test phrase",
                         password_confirm="private test phrase"),
        language="en_US",
    )
    errors, results = [], []
    job.failed.connect(errors.append)
    job.succeeded.connect(results.append)
    with qtbot.waitSignal(job.finished, timeout=10000):
        job.start()
    qtbot.waitUntil(lambda: bool(errors))
    assert not results
    assert not target.exists()
    assert "private test phrase" not in errors[0]
    assert not any("\u4e00" <= character <= "\u9fff" for character in errors[0])
    assert job.request is None
