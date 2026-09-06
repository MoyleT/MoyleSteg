"""Synthetic replacements at the credential/open boundary, with real decoding."""

import os
from pathlib import Path

import pytest
from PIL import Image

import png_steg_aes256 as core
from moyle_steg import service


@pytest.fixture(params=["png", "saes"])
def containers(tmp_path, request):
    key = tmp_path / "demo.key"
    core.generate_key_file(key)
    credential = core.Credential.from_key_file(key)
    secret = tmp_path / "payload.txt"
    secret.write_bytes(b"synthetic original")
    small = tmp_path / ("input." + request.param)
    large = tmp_path / ("replacement." + request.param)
    if request.param == "png":
        cover = tmp_path / "cover.png"
        Image.new("RGB", (96, 96), "#645588").save(cover)
        core.hide_file(cover, secret, small, credential=credential)
        large.write_bytes(small.read_bytes() + b"synthetic trailer" * 8192)
        payload = secret.read_bytes()
    else:
        core.encrypt_file(secret, small, credential=credential)
        secret.write_bytes(os.urandom(128 * 1024))
        core.encrypt_file(secret, large, credential=credential)
        payload = secret.read_bytes()
    assert small.stat().st_size < 4096 < large.stat().st_size
    return small, large, key, credential, payload


@pytest.mark.parametrize("destination", ["manual", "original", "verify", "inspect"])
@pytest.mark.parametrize("raised_budget", [False, True])
def test_replacement_after_credentials_checks_actual_container(containers, tmp_path, monkeypatch,
                                                               destination, raised_budget):
    small, large, key, _, payload = containers
    operation = "extract" if small.suffix == ".png" else "decrypt"
    output = tmp_path / "restored.txt"
    folder = tmp_path / "original-name"
    request = service.OperationRequest(
        operation=destination if destination in {"verify", "inspect"} else operation,
        input_path=str(small), key_path=str(key), credential_mode="key_file",
        output_path=str(output) if destination == "manual" else "",
        output_directory=str(folder) if destination == "original" else "",
        max_container_bytes=large.stat().st_size if raised_budget else 4096,
    )
    original = service._credential
    changed = []

    def replace_after_credential(*args, **kwargs):
        credential = original(*args, **kwargs)
        os.replace(large, small)
        changed.append(True)
        return credential

    monkeypatch.setattr(service, "_credential", replace_after_credential)
    if raised_budget:
        result = service.execute(request)
        if destination in {"verify", "inspect"}:
            assert result.details["verified"] == "yes"
        else:
            assert Path(result.output_path).read_bytes() == payload
    else:
        with pytest.raises(core.StegError) as caught:
            service.execute(request)
        assert getattr(caught.value, "code", "") == "container_resource_limit"
        assert "容器" in service.friendly_error(caught.value)
        assert "container" in service.friendly_error(caught.value, "en_US")
        assert not output.exists() and not folder.exists()
    assert changed == [True]


@pytest.mark.parametrize("force", [False, True])
def test_oversize_does_not_write_manual_destination(containers, tmp_path, force):
    _, large, key, _, _ = containers
    output = tmp_path / "existing.txt"
    if force:
        output.write_bytes(b"keep existing output")
    operation = "extract" if large.suffix == ".png" else "decrypt"
    with pytest.raises(core.StegError) as caught:
        service.execute(service.OperationRequest(operation=operation, input_path=str(large),
            output_path=str(output), credential_mode="key_file", key_path=str(key),
            max_container_bytes=4096, force=force))
    assert getattr(caught.value, "code", "") == "container_resource_limit"
    assert output.read_bytes() == b"keep existing output" if force else not output.exists()


@pytest.mark.parametrize("entry", ["peek", "decode", "restore"])
def test_core_budget_rejects_then_accepts_exact_opened_size(containers, tmp_path, entry):
    _, large, _, credential, payload = containers
    png = large.suffix == ".png"
    call = {"peek": core.peek_header if png else core.peek_encrypted_header,
            "decode": core.decode_image if png else core.decode_encrypted_file,
            "restore": core.extract_file if png else core.decrypt_encrypted_file}[entry]
    kwargs = {} if entry == "peek" else {"credential": credential}
    output = tmp_path / "core-restored.txt"
    args = (large, output) if entry == "restore" else (large,)
    with pytest.raises(core.StegError) as caught:
        call(*args, max_container_bytes=4096, **kwargs)
    assert getattr(caught.value, "code", "") == "container_resource_limit"
    assert not output.exists()
    result = call(*args, max_container_bytes=large.stat().st_size, **kwargs)
    if entry == "decode":
        assert result.data == payload
    if entry == "restore":
        assert output.read_bytes() == payload


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_core_invalid_budget_is_consistent(containers, budget):
    small, _, _, credential, _ = containers
    decode = core.decode_image if small.suffix == ".png" else core.decode_encrypted_file
    with pytest.raises(ValueError) as caught:
        decode(small, credential=credential, max_container_bytes=budget)
    assert getattr(caught.value, "code", "") == "container_budget_invalid"


def test_opened_object_is_checked_even_when_original_path_is_small(containers, monkeypatch):
    small, large, _, credential, _ = containers
    original = Path.open
    def different_open(self, mode="r", *args, **kwargs):
        return original(large if self == small and mode == "rb" else self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", different_open)
    decode = core.decode_image if small.suffix == ".png" else core.decode_encrypted_file
    with pytest.raises(core.StegError) as caught:
        decode(small, credential=credential, max_container_bytes=4096)
    assert getattr(caught.value, "code", "") == "container_resource_limit"
    assert small.stat().st_size < 4096


@pytest.mark.parametrize("checkpoint", ["image_callback", "decoder_read"])
def test_png_growth_after_open_is_rejected_before_output(tmp_path, monkeypatch, checkpoint):
    secret, cover, container, output = (tmp_path / name for name in
        ("payload.txt", "cover.png", "container.png", "restored.txt"))
    secret.write_bytes(b"synthetic growing input")
    Image.new("RGB", (96, 96), "#654588").save(cover)
    credential = core.Credential.from_password("demo")
    core.hide_file(cover, secret, container, credential=credential)
    original_open = Path.open
    changed = []
    def grow():
        if not changed:
            with original_open(container, "ab") as stream:
                stream.write(b"tail" * 4096)
            changed.append(True)
    def progress(stage, done, total):
        if checkpoint == "image_callback" and stage == "image":
            grow()
    class GrowingFile:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            data = self.stream.read(size)
            grow()
            return data
    def growing_open(self, mode="r", *args, **kwargs):
        stream = original_open(self, mode, *args, **kwargs)
        return GrowingFile(stream) if self == container and mode == "rb" else stream
    if checkpoint == "decoder_read":
        monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(core.StegError) as caught:
        core.extract_file(container, output, credential=credential, max_container_bytes=4096,
                          control=core.OperationControl(progress=progress))
    assert changed and getattr(caught.value, "code", "") == "container_resource_limit"
    assert not output.exists()
