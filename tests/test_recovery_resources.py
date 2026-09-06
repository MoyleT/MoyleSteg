"""Synthetic recovery budgets and result provenance at the Qt-free boundary."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import png_steg_aes256 as core
from moyle_steg import service


@pytest.fixture
def png_container(tmp_path):
    source, cover, container = (tmp_path / name for name in ("payload.txt", "cover.png", "container.png"))
    source.write_bytes(b"synthetic recovery payload" * 20)
    Image.new("RGB", (96, 96), "#654598").save(cover)
    core.hide_file(cover, source, container, credential=core.Credential.from_password("synthetic password"))
    return source, cover, container


@pytest.mark.parametrize("operation", ["extract", "verify", "inspect"])
def test_recovery_pixel_budget_error_preserves_container_advice(png_container, operation):
    source, _, container = png_container
    original = container.read_bytes()
    request = service.OperationRequest(operation=operation, input_path=str(container),
        output_path=str(container.parent / "restored.txt") if operation == "extract" else "",
        password="synthetic password", max_pixels=1024)
    with pytest.raises(core.StegError) as caught:
        service.execute(request)
    assert getattr(caught.value, "code", "") == "recovery_resource_limit"
    assert "请勿缩放" in service.friendly_error(caught.value)
    assert "re-save" in service.friendly_error(caught.value, "en_US")
    request.max_pixels = 96 * 96
    result = service.execute(request)
    assert result.details["payload_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert container.read_bytes() == original


def test_preflight_resource_advice_still_applies_to_secret_input(png_container):
    source, cover, _ = png_container
    with pytest.raises(core.StegError) as caught:
        service.execute(service.OperationRequest(operation="preflight", input_path=str(source),
            cover_path=str(cover), max_file_bytes=1))
    assert "秘密文件" in service.friendly_error(caught.value)
    assert "smaller secret file" in service.friendly_error(caught.value, "en_US")


@pytest.mark.parametrize("operation", ["verify", "inspect", "extract"])
def test_trailing_png_bytes_exceed_container_budget_before_capture(png_container, monkeypatch, operation):
    _, _, container = png_container
    with container.open("ab") as stream:
        stream.write(b"a" * (8 * 1024 * 1024))
    before = container.stat()
    temporary_directory = service.TemporaryDirectory
    def forbidden(**kwargs):
        pytest.fail("allocated temporary storage before rejecting complete container size")
    monkeypatch.setattr(service, "TemporaryDirectory", forbidden)
    request = service.OperationRequest(operation=operation, input_path=str(container),
        output_path=str(container.parent / "never.txt") if operation == "extract" else "",
        password="wrong password", max_file_bytes=4096)
    request.max_container_bytes = 1024 * 1024
    with pytest.raises(core.StegError) as caught:
        service.execute(request)
    assert getattr(caught.value, "code", "") == "container_resource_limit"
    assert "容器" in service.friendly_error(caught.value)
    assert container.stat().st_size == before.st_size
    assert container.stat().st_mtime_ns == before.st_mtime_ns
    assert not (container.parent / "never.txt").exists()
    # Raising only the independent container budget restores this same file.
    monkeypatch.setattr(service, "TemporaryDirectory", temporary_directory)
    request.password = "synthetic password"
    request.max_container_bytes = before.st_size
    result = service.execute(request)
    assert result.details["payload_sha256"] == sha256(png_container[0].read_bytes()).hexdigest()
    if operation in {"verify", "inspect"}:
        assert result.details["input_sha256"] == sha256(container.read_bytes()).hexdigest()


def test_disk_budget_rejected_before_capture(png_container, monkeypatch):
    _, _, container = png_container
    # A free-space probe is the OS boundary; the actual capture remains real.
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(total=100_000, used=99_999, free=1))
    def forbidden(**kwargs):
        pytest.fail("allocated capture directory despite inadequate temporary free space")
    monkeypatch.setattr(service, "TemporaryDirectory", forbidden)
    with pytest.raises(OSError) as caught:
        service.execute(service.OperationRequest(operation="verify", input_path=str(container), password="synthetic password"))
    assert getattr(caught.value, "code", "") == "temporary_space"
    assert "临时" in service.friendly_error(caught.value)
    assert "temporary" in service.friendly_error(caught.value, "en_US")


def test_probe_reports_temp_requirement_without_reading_container(png_container, monkeypatch):
    _, _, container = png_container
    size = container.stat().st_size
    probe = getattr(service, "probe_recovery_resources", None)
    assert callable(probe), "UI needs a Qt-free metadata-only disk budget probe"
    def forbidden(*args, **kwargs):
        pytest.fail("resource probe read file contents")
    monkeypatch.setattr(Path, "open", forbidden)
    report = probe(str(container), operation="verify")
    assert report.input_size == size
    assert report.temporary_required == size + 16 * 1024 * 1024
    assert report.temporary_free > 0
    assert Path(report.temporary_directory).is_dir()
    assert probe(str(container), operation="extract").temporary_required == 0


def test_success_context_uses_executed_input_and_timezone(png_container, monkeypatch):
    _, _, container = png_container
    monkeypatch.chdir(container.parent)
    request = service.OperationRequest(operation="verify", input_path=container.name, password="synthetic password")
    start = datetime.now().astimezone().replace(microsecond=0)
    def change_request(stage, done, total):
        request.input_path = str(container.parent / "unverified.png")
    result = service.execute(request, control=core.OperationControl(progress=change_request))
    assert getattr(result, "input_path", "") == str(container.absolute())
    completed = datetime.fromisoformat(result.completed_at)
    assert completed.tzinfo is not None and completed >= start
    assert "synthetic password" not in repr(result)


def test_disk_full_during_capture_is_localized_and_cleaned(png_container, monkeypatch):
    _, _, container = png_container
    original_open = Path.open
    capture_paths = []
    class DiskFullWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, data):
            raise OSError(28, "synthetic disk full")
    def failing_open(self, mode="r", *args, **kwargs):
        stream = original_open(self, mode, *args, **kwargs)
        if mode == "xb" and self.name == "container":
            capture_paths.append(self)
            return DiskFullWriter(stream)
        return stream
    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(OSError) as caught:
        service.execute(service.OperationRequest(operation="verify", input_path=str(container), password="synthetic password"))
    assert getattr(caught.value, "code", "") == "temporary_space"
    assert capture_paths and all(not path.parent.exists() for path in capture_paths)


def test_decrypt_container_budget_checked_before_decode(tmp_path):
    source, encoded, restored = (tmp_path / name for name in ("payload.txt", "payload.saes", "restored.txt"))
    source.write_bytes(b"synthetic decrypt budget")
    core.encrypt_file(source, encoded, credential=core.Credential.from_password("synthetic password"))
    request = service.OperationRequest(operation="decrypt", input_path=str(encoded), output_path=str(restored), password="wrong")
    request.max_container_bytes = 1
    with pytest.raises(core.StegError) as caught:
        service.execute(request)
    assert getattr(caught.value, "code", "") == "container_resource_limit"
    assert not restored.exists()


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_container_budget_does_not_start_capture(png_container, monkeypatch, budget):
    _, _, container = png_container
    def forbidden(**kwargs):
        pytest.fail("capture started with an invalid container budget")
    monkeypatch.setattr(service, "TemporaryDirectory", forbidden)
    with pytest.raises(ValueError) as caught:
        service.execute(service.OperationRequest(operation="verify", input_path=str(container),
            password="synthetic password", max_container_bytes=budget))
    assert getattr(caught.value, "code", "") == "container_budget_invalid"


def test_container_growth_between_stat_and_open_rechecks_budget(png_container, monkeypatch):
    _, _, container = png_container
    original_open = Path.open
    grown = []
    def grow_before_open(self, mode="r", *args, **kwargs):
        if self == container and mode == "rb" and not grown:
            with original_open(self, "ab") as stream:
                stream.write(b"synthetic growth" * 10_000)
            grown.append(True)
        return original_open(self, mode, *args, **kwargs)
    def forbidden(**kwargs):
        pytest.fail("capture started after container grew beyond its byte budget")
    monkeypatch.setattr(Path, "open", grow_before_open)
    monkeypatch.setattr(service, "TemporaryDirectory", forbidden)
    with pytest.raises(core.StegError) as caught:
        service.execute(service.OperationRequest(operation="verify", input_path=str(container),
            password="synthetic password", max_container_bytes=container.stat().st_size))
    assert grown and getattr(caught.value, "code", "") == "container_resource_limit"
