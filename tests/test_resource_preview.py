"""Background resource previews must remain responsive and bind to one input."""
from pathlib import Path
from threading import Event, Lock

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from moyle_steg import recovery, service
from moyle_steg.service import OperationRequest, RecoveryResources, execute
from moyle_steg.worker import JobThread
from moyle_steg import worker


def test_slow_probe_runs_off_ui_and_only_latest_input_is_displayed(qtbot, tmp_path, monkeypatch):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    started, release = Event(), Event()
    active, maximum, calls = [0], [0], []
    lock = Lock()
    def probe(path, *, operation):
        assert QThread.currentThread() != QApplication.instance().thread(), "metadata probe blocked the GUI thread"
        with lock:
            active[0] += 1
            maximum[0] = max(maximum[0], active[0])
        calls.append((path, operation))
        if path == str(a):
            started.set()
            assert release.wait(5)
        with lock:
            active[0] -= 1
        return RecoveryResources(11 if path == str(a) else 22, 100, 1000, str(tmp_path))
    monkeypatch.setattr(recovery, "probe_recovery_resources", probe)
    panel = recovery.RecoveryBudgetPanel()
    qtbot.addWidget(panel)
    panel.set_input(str(a))
    panel.refresh_resources()
    try:
        qtbot.waitUntil(started.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        panel.set_input(str(b))
        panel.refresh_resources()
        assert panel._resources is None
    finally:
        release.set()
    qtbot.waitUntil(lambda: panel._resources is not None and panel._resources.input_size == 22)
    assert calls == [(str(a), "verify"), (str(b), "verify")]
    assert maximum == [1]
    assert "22.0 B" in panel.resources_label.text()


def test_formal_resource_snapshot_supersedes_inflight_preview(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "input.png"
    started, release = Event(), Event()
    def probe(value, *, operation):
        assert QThread.currentThread() != QApplication.instance().thread()
        started.set()
        assert release.wait(5)
        return RecoveryResources(1, 100, 1000, str(tmp_path))
    monkeypatch.setattr(recovery, "probe_recovery_resources", probe)
    panel = recovery.RecoveryBudgetPanel()
    qtbot.addWidget(panel)
    panel.set_input(str(path), "inspect")
    panel.refresh_resources()
    try:
        qtbot.waitUntil(started.is_set)
        display = getattr(panel, "display_resources", None)
        assert callable(display), "worker needs a non-blocking formal snapshot display API"
        display(RecoveryResources(500, 0, 1000, str(tmp_path)), str(path), "extract")
    finally:
        release.set()
    qtbot.wait(100)
    assert panel._resources.input_size == 500
    assert "临时空间" not in panel.resources_label.text()


def test_resource_input_path_uses_execution_normalization(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    calls = []
    def probe(path, *, operation):
        calls.append(path)
        return RecoveryResources(20, 0, 1000, str(tmp_path))
    monkeypatch.setattr(recovery, "probe_recovery_resources", probe)
    panel = recovery.RecoveryBudgetPanel()
    qtbot.addWidget(panel)
    panel.set_input("~/input.png", "extract")
    panel.refresh_resources()
    qtbot.waitUntil(lambda: bool(calls))
    assert calls == [str((tmp_path / "input.png").absolute())]


def _container(tmp_path):
    source, container = tmp_path / "payload.txt", tmp_path / "input.saes"
    source.write_bytes(b"synthetic resource acknowledgement")
    execute(OperationRequest("encrypt", input_path=str(source), output_path=str(container),
        password="synthetic password", password_confirm="synthetic password"))
    return container


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_waits_for_resource_display_ack_before_capture(qtbot, tmp_path, monkeypatch, cancel):
    container = _container(tmp_path)
    assert hasattr(JobThread, "resource_ready"), "GUI must see resources before the worker allocates a private copy"
    job = JobThread(OperationRequest("verify", input_path=str(container), password="synthetic password"), resource_preview=True)
    previews, results, errors, cancelled, capture = [], [], [], [], []
    temporary_directory = service.TemporaryDirectory
    def track_capture(**kwargs):
        capture.append(True)
        return temporary_directory(**kwargs)
    monkeypatch.setattr(service, "TemporaryDirectory", track_capture)
    job.resource_ready.connect(previews.append)
    job.succeeded.connect(results.append)
    job.failed.connect(errors.append)
    job.cancelled.connect(lambda: cancelled.append(True))
    job.start()
    try:
        qtbot.waitUntil(lambda: bool(previews), timeout=10000)
        qtbot.wait(60)
        assert not capture and job.isRunning()
        assert previews[0].input_size == container.stat().st_size
        if cancel:
            job.request_cancel()
        else:
            job.acknowledge_resources()
        qtbot.waitUntil(lambda: not job.isRunning(), timeout=15000)
        qtbot.waitUntil(lambda: bool(cancelled if cancel else results))
        assert not errors
        if cancel:
            assert not capture and not results
        else:
            assert capture and results[0].details["verified"] == "yes"
        assert job.request is None
    finally:
        job.request_cancel()
        job.wait(15000)


def test_deleting_panel_with_running_preview_does_not_destroy_a_thread(qtbot, tmp_path, monkeypatch):
    started, release, completed = Event(), Event(), Event()
    def probe(path, *, operation):
        assert QThread.currentThread() != QApplication.instance().thread()
        started.set()
        assert release.wait(5)
        completed.set()
        return RecoveryResources(11, 100, 1000, str(tmp_path))
    monkeypatch.setattr(recovery, "probe_recovery_resources", probe)
    panel = recovery.RecoveryBudgetPanel()
    panel.set_input(str(tmp_path / "input.png"))
    panel.refresh_resources()
    try:
        qtbot.waitUntil(started.is_set)
        panel.deleteLater()
        qtbot.wait(30)
    finally:
        release.set()
    qtbot.waitUntil(completed.is_set)
    qtbot.wait(30)


def test_cancel_during_slow_probe_never_requests_ack_or_starts_capture(qtbot, tmp_path, monkeypatch):
    container = _container(tmp_path)
    started, release = Event(), Event()
    real_probe = worker.probe_recovery_resources
    def slow_probe(path, *, operation):
        started.set()
        assert release.wait(5)
        return real_probe(path, operation=operation)
    def forbidden(**kwargs):
        pytest.fail("cancelled resource probe started an encrypted capture")
    monkeypatch.setattr(worker, "probe_recovery_resources", slow_probe)
    monkeypatch.setattr(service, "TemporaryDirectory", forbidden)
    job = JobThread(OperationRequest("verify", input_path=str(container), password="synthetic password"), resource_preview=True)
    previews, cancelled, errors = [], [], []
    job.resource_ready.connect(previews.append)
    job.cancelled.connect(lambda: cancelled.append(True))
    job.failed.connect(errors.append)
    job.start()
    try:
        qtbot.waitUntil(started.is_set)
        job.request_cancel()
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
    finally:
        release.set()
        job.wait(10000)
    qtbot.waitUntil(lambda: bool(cancelled))
    assert not previews and not errors and job.request is None


def test_preview_probe_failure_finishes_without_waiting_for_ack(qtbot, tmp_path):
    job = JobThread(OperationRequest("verify", input_path=str(tmp_path / "missing.png"), password="synthetic password"),
                    resource_preview=True, language="en_US")
    previews, errors, results = [], [], []
    job.resource_ready.connect(previews.append)
    job.failed.connect(errors.append)
    job.succeeded.connect(results.append)
    with qtbot.waitSignal(job.finished, timeout=10000):
        job.start()
    qtbot.waitUntil(lambda: bool(errors))
    assert "not found" in errors[0]
    assert not previews and not results and job.request is None


def test_existing_worker_api_verifies_without_resource_ack(qtbot, tmp_path):
    container = _container(tmp_path)
    job = JobThread(OperationRequest("verify", input_path=str(container), password="synthetic password"))
    previews, results = [], []
    job.resource_ready.connect(previews.append)
    job.succeeded.connect(results.append)
    with qtbot.waitSignal(job.finished, timeout=15000):
        job.start()
    qtbot.waitUntil(lambda: bool(results))
    assert not previews and results[0].details["verified"] == "yes"
