"""Verification must associate authentication and the full-container digest."""
import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image

import png_steg_aes256 as core
from moyle_steg.service import OperationRequest, execute
from moyle_steg import service


@pytest.fixture(params=['png', 'saes'])
def container(request, tmp_path):
    source = tmp_path / '合成载荷.txt'
    source.write_bytes(b'synthetic verification association\n' * 100)
    credential = core.Credential.from_password('synthetic verify password')
    target = tmp_path / ('input.' + request.param)
    if request.param == 'png':
        cover = tmp_path / 'cover.png'
        Image.new('RGB', (96, 96), '#496858').save(cover)
        core.hide_file(cover, source, target, credential=credential)
    else:
        core.encrypt_file(source, target, credential=credential)
    return request.param, target, source.read_bytes(), credential


@pytest.mark.parametrize('operation', ['verify', 'inspect'])
@pytest.mark.parametrize('restore_mtime', [False, True])
def test_result_never_pairs_authenticated_a_with_corrupted_b(container, operation, restore_mtime):
    kind, path, payload, credential = container
    original = path.read_bytes()
    initial = path.stat()
    modified = []

    def change_original(stage, completed, total):
        if stage == 'hash' and completed == 0 and not modified:
            broken = bytearray(original)
            broken[0 if kind == 'png' else -1] ^= 1
            path.write_bytes(broken)
            if restore_mtime:
                os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            else:
                os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 4_000_000_000))
            modified.append(True)

    try:
        result = execute(OperationRequest(operation=operation, input_path=str(path),
                         password='synthetic verify password'),
                         control=core.OperationControl(progress=change_original))
    except (ValueError, core.StegError) as error:
        assert getattr(error, 'code', '') == 'input_changed'
    else:
        # A consistent captured A is valid, even if original-path B changed later.
        assert restore_mtime
        assert result.details['verified'] == 'yes'
        assert result.details['payload_sha256'] == hashlib.sha256(payload).hexdigest()
        assert result.details['input_sha256'] == hashlib.sha256(original).hexdigest()
        assert result.details['input_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest()
    assert modified
    decode = core.decode_image if kind == 'png' else core.decode_encrypted_file
    with pytest.raises(core.StegError):
        decode(path, credential=credential)


@pytest.mark.parametrize('operation', ['verify', 'inspect'])
def test_stable_container_both_digests_match_and_no_recovery_is_written(container, operation):
    kind, path, payload, _ = container
    before = {p: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    result = execute(OperationRequest(operation=operation, input_path=str(path), password='synthetic verify password'))
    assert result.details['container_format'] == kind and result.details['verified'] == 'yes'
    assert result.details['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert result.details['input_sha256'] == hashlib.sha256(before[path]).hexdigest()
    assert result.output_path == ''
    assert {p: p.read_bytes() for p in path.parent.iterdir() if p.is_file()} == before


def test_original_path_is_opened_once_for_controlled_capture(container, monkeypatch):
    _, path, _, _ = container
    original_open = Path.open
    reads = []
    def guarded_open(self, mode='r', *args, **kwargs):
        if self == path and 'r' in mode:
            reads.append(mode)
            assert len(reads) == 1, 'verification reopened mutable source bytes'
        return original_open(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    result = execute(OperationRequest(operation='verify', input_path=str(path), password='synthetic verify password'))
    assert result.details['verified'] == 'yes' and reads == ['rb']


def test_private_copy_change_after_authentication_is_rejected(container, monkeypatch):
    kind, path, _, _ = container
    name = 'decode_image' if kind == 'png' else 'decode_encrypted_file'
    decode = getattr(service, name)
    def alter_authenticated_copy(copy, **kwargs):
        decoded = decode(copy, **kwargs)
        assert copy != path
        before = copy.stat()
        content = bytearray(copy.read_bytes())
        content[-1] ^= 1
        copy.write_bytes(content)
        os.utime(copy, ns=(before.st_atime_ns, before.st_mtime_ns))
        return decoded
    monkeypatch.setattr(service, name, alter_authenticated_copy)
    with pytest.raises(ValueError) as caught:
        execute(OperationRequest(operation='verify', input_path=str(path), password='synthetic verify password'))
    assert getattr(caught.value, 'code', '') == 'input_changed'


@pytest.mark.parametrize('outcome', ['success', 'wrong_password', 'capture', 'hash', 'derive', 'disk_error'])
def test_temporary_encrypted_copy_is_cleaned_on_every_exit(container, tmp_path, monkeypatch, outcome):
    kind, path, _, _ = container
    original_bytes, original_mtime = path.read_bytes(), path.stat().st_mtime_ns
    before = set(tmp_path.iterdir())
    temporary_directory = service.TemporaryDirectory
    directories = []
    def tracked_directory(**kwargs):
        directory = temporary_directory(dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory
    monkeypatch.setattr(service, 'TemporaryDirectory', tracked_directory)
    if outcome == 'disk_error':
        original_open = Path.open
        class DiskFullWriter:
            def __init__(self, handle):
                self.handle = handle
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def write(self, data):
                self.handle.write(data[:10])
                raise OSError(28, 'synthetic disk full')
        def fail_copy(self, mode='r', *args, **kwargs):
            handle = original_open(self, mode, *args, **kwargs)
            return DiskFullWriter(handle) if mode == 'xb' and self.name == 'container' else handle
        monkeypatch.setattr(Path, 'open', fail_copy)
    cancelled = []
    def progress(stage, done, total):
        # Both decoders expose decrypt; only PNG has a separate derive stage.
        cancel_stage = 'decrypt' if outcome == 'derive' and kind == 'saes' else outcome
        if stage == cancel_stage:
            cancelled.append(True)
    control = core.OperationControl(progress=progress, cancelled=lambda: bool(cancelled))
    request = OperationRequest(operation='verify', input_path=str(path),
        password='wrong password' if outcome == 'wrong_password' else 'synthetic verify password')
    if outcome == 'success':
        assert execute(request, control=control).details['verified'] == 'yes'
    else:
        error = OSError if outcome == 'disk_error' else core.AuthenticationError if outcome == 'wrong_password' else core.OperationCancelled
        with pytest.raises(error):
            execute(request, control=control)
    assert directories and all(not directory.exists() for directory in directories)
    assert set(tmp_path.iterdir()) == before
    assert path.read_bytes() == original_bytes and path.stat().st_mtime_ns == original_mtime


def test_png_full_digest_includes_large_trailing_data_beyond_payload_budget(tmp_path):
    source, cover, encoded = tmp_path/'small.txt', tmp_path/'cover.png', tmp_path/'image.png'
    payload = b'synthetic small payload' * 10
    source.write_bytes(payload)
    Image.new('RGB', (96, 96), '#496858').save(cover)
    core.hide_file(cover, source, encoded, credential=core.Credential.from_password('test password'))
    with encoded.open('ab') as stream:
        stream.write(b'public trailing bytes' * 100_000)
    result = execute(OperationRequest(operation='verify', input_path=str(encoded), password='test password',
                                     max_file_bytes=len(payload)))
    assert result.details['input_sha256'] == hashlib.sha256(encoded.read_bytes()).hexdigest()
    assert int(result.details['input_size']) == encoded.stat().st_size


@pytest.mark.parametrize('kind', ['png', 'saes'])
def test_known_resource_excess_rejected_before_copy_storage(tmp_path, monkeypatch, kind):
    path = tmp_path / ('oversized.' + kind)
    if kind == 'png':
        Image.new('RGB', (64, 64), '#496858').save(path)
    else:
        header = core._build_header(core.MODE_PASSWORD, b's'*16, b'n'*12, 100_000)
        path.write_bytes(core._serialize_header(header) + b'x'*100_000)
    def forbidden(**kwargs):
        pytest.fail('temporary disk storage allocated before known resource rejection')
    monkeypatch.setattr(service, 'TemporaryDirectory', forbidden)
    with pytest.raises(core.StegError):
        execute(OperationRequest(operation='verify', input_path=str(path), password='test password',
                                 max_pixels=1024, max_file_bytes=1))


@pytest.mark.parametrize('fixture', ['legacy-v1.png', 'legacy-v1.saes', 'legacy-posix-name.saes'])
def test_readonly_copy_verifies_legacy_metadata(fixture):
    path = Path(__file__).parent/'fixtures'/fixture
    result = execute(OperationRequest(operation='verify', input_path=str(path), password='legacy fixture password'))
    assert result.details['verified'] == 'yes'
    assert result.details['input_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    if fixture == 'legacy-posix-name.saes':
        assert result.details['filename'] == 'file:note.txt'


def test_invalid_file_budget_rejected_before_copy_storage(container, monkeypatch):
    _, path, _, _ = container
    def forbidden(**kwargs):
        pytest.fail('copy storage allocated with invalid resource budget')
    monkeypatch.setattr(service, 'TemporaryDirectory', forbidden)
    with pytest.raises(ValueError):
        execute(OperationRequest(operation='verify', input_path=str(path), password='synthetic verify password',
                                 max_file_bytes=0))


def test_key_file_verification_preserves_both_digest_contracts(container):
    kind, path, payload, _ = container
    key = path.parent / 'synthetic.stegkey'
    core.generate_key_file(key)
    credential = core.Credential.from_key_file(key)
    source = path.parent / '合成载荷.txt'
    if kind == 'png':
        core.hide_file(path.parent/'cover.png', source, path, credential=credential, force=True)
    else:
        core.encrypt_file(source, path, credential=credential, force=True)
    result = execute(OperationRequest(operation='verify', input_path=str(path),
                                     credential_mode='key_file', key_path=str(key)))
    assert result.details['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert result.details['input_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_capture_does_not_follow_input_growth(container):
    _, path, _, _ = container
    initial = path.stat()
    modified = []
    def grow(stage, done, total):
        if stage == 'capture' and done and not modified:
            with path.open('ab') as stream:
                stream.write(b'growth' * 200_000)
            os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            modified.append(True)
    with pytest.raises(ValueError) as caught:
        execute(OperationRequest(operation='verify', input_path=str(path), password='synthetic verify password'),
                control=core.OperationControl(progress=grow))
    assert getattr(caught.value, 'code', '') == 'input_changed' and modified
