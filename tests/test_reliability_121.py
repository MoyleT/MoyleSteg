"""Synthetic regressions for failed-job effects, changing inputs and long names."""
import os
from pathlib import Path

import pytest
from PIL import Image
import png_steg_aes256 as core


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'A' * (2 * core.IO_CHUNK))
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (256, 256), '#446655').save(cover)
    return source, cover, core.Credential.from_password('synthetic reliability password')


@pytest.mark.parametrize('command', ['encrypt', 'hide'])
def test_combined_job_never_replaces_existing_key(sample, tmp_path, command, monkeypatch):
    source, cover, _ = sample
    key = tmp_path / 'existing.stegkey'
    core.generate_key_file(key)
    old_bytes = key.read_bytes()
    credential = core.Credential.from_key_file(key)
    historical = tmp_path / 'historical.saes'
    core.encrypt_file(source, historical, credential=credential)
    output = tmp_path / ('output.png' if command == 'hide' else 'output.saes')
    # Force a later save failure; no capacity preflight could prevent this class.
    monkeypatch.setattr(core, command + '_file', lambda *a, **k: (_ for _ in ()).throw(OSError('injected save failure')))
    args = [command] + ([str(cover), str(source)] if command == 'hide' else [str(source)])
    assert core.main(args + [str(output), '--new-key-file', str(key), '--force-key']) == 2
    assert key.read_bytes() == old_bytes
    assert core.decode_encrypted_file(historical, credential=core.Credential.from_key_file(key)).data == source.read_bytes()
    assert not output.exists()


def test_failed_new_key_job_reports_retained_key(sample, tmp_path, monkeypatch, capsys):
    source, _, _ = sample
    key, output = tmp_path / 'new.stegkey', tmp_path / 'output.saes'
    monkeypatch.setattr(core, 'encrypt_file', lambda *a, **k: (_ for _ in ()).throw(OSError('injected save failure')))
    assert core.main(['encrypt', str(source), str(output), '--new-key-file', str(key)]) == 2
    assert len(core.read_key_file(key)) == 32
    assert not output.exists()
    error = capsys.readouterr().err
    assert str(key) in error and '保留' in error


@pytest.mark.parametrize('operation', ['encrypt', 'hide', 'preflight'])
@pytest.mark.parametrize('mutation', ['overwrite', 'truncate', 'grow', 'restore_mtime'])
def test_changing_source_never_succeeds_with_mixed_content(sample, tmp_path, operation, mutation):
    source, cover, credential = sample
    before = source.stat()
    changed = []
    def progress(stage, done, total):
        if stage == 'read' and done == core.IO_CHUNK and not changed:
            changed.append(True)
            if mutation == 'truncate':
                source.write_bytes(b'B' * core.IO_CHUNK)
            elif mutation == 'grow':
                with source.open('ab') as stream:
                    stream.write(b'B')
            else:
                source.write_bytes(b'B' * (2 * core.IO_CHUNK))
                if mutation == 'restore_mtime':
                    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    output = tmp_path / ('result.png' if operation == 'hide' else 'result.saes')
    control = core.OperationControl(progress=progress)
    with pytest.raises(core.StegError) as caught:
        if operation == 'encrypt':
            core.encrypt_file(source, output, credential=credential, control=control)
        elif operation == 'hide':
            core.hide_file(cover, source, output, credential=credential, control=control)
        else:
            core.preflight_hide(cover, source, control=control)
    assert getattr(caught.value, 'code', '') == 'input_changed'
    assert changed and not output.exists()


@pytest.mark.parametrize('kind', ['saes', 'png', 'key', 'plain'])
def test_long_valid_output_names_use_short_temporary_names(sample, tmp_path, kind):
    source, cover, credential = sample
    suffix = {'saes': '.saes', 'png': '.png', 'key': '.stegkey', 'plain': '.txt'}[kind]
    output = tmp_path / ('x' * (249 - len(suffix)) + suffix)
    if os.name == 'nt':
        # Test the component limit without conflating it with legacy MAX_PATH.
        output = Path('\\\\?\\' + str(output.resolve()))
    # Establish that the final name itself is supported by this filesystem.
    try:
        output.write_bytes(b'previous ordinary output')
    except OSError as exc:
        pytest.skip(f'Platform does not support this final test path: {exc.errno}')
    if kind == 'saes':
        core.encrypt_file(source, output, credential=credential, force=True)
        assert core.decode_encrypted_file(output, credential=credential).data == source.read_bytes()
    elif kind == 'png':
        core.hide_file(cover, source, output, credential=credential, force=True)
        assert core.decode_image(output, credential=credential).data == source.read_bytes()
    elif kind == 'key':
        key = core.generate_key_file(output, force=True)
        assert core.read_key_file(output) == key
    else:
        core._atomic_write(output, b'restored data', force=True)
        assert output.read_bytes() == b'restored data'


def test_source_change_error_is_bilingual_and_actionable():
    from moyle_steg.service import friendly_error
    error = core.StegError('synthetic error')
    error.code = 'input_changed'
    assert '保存' in friendly_error(error, 'zh_CN')
    assert 'sav' in friendly_error(error, 'en_US').lower()


@pytest.mark.parametrize('command', ['encrypt', 'hide'])
def test_combined_job_new_key_roundtrip(sample, tmp_path, command):
    source, cover, _ = sample
    key = tmp_path / 'new.stegkey'
    output = tmp_path / ('result.png' if command == 'hide' else 'result.saes')
    args = [command] + ([str(cover), str(source)] if command == 'hide' else [str(source)])
    assert core.main(args + [str(output), '--new-key-file', str(key)]) == 0
    decode = core.decode_image if command == 'hide' else core.decode_encrypted_file
    assert decode(output, credential=core.Credential.from_key_file(key)).data == source.read_bytes()
    saved_key, saved_output = key.read_bytes(), output.read_bytes()
    assert core.main(args + [str(output), '--new-key-file', str(key), '--force']) == 2
    assert key.read_bytes() == saved_key and output.read_bytes() == saved_output


def test_standalone_explicit_key_replacement_still_works(tmp_path):
    key = tmp_path / 'replace.stegkey'
    assert core.main(['keygen', str(key)]) == 0
    before = core.read_key_file(key)
    assert core.main(['keygen', str(key), '--force']) == 0
    assert len(core.read_key_file(key)) == 32 and core.read_key_file(key) != before


def test_cancelled_new_key_job_reports_retained_key(sample, tmp_path, monkeypatch, capsys):
    source, _, _ = sample
    key, output = tmp_path / 'cancel.stegkey', tmp_path / 'result.saes'
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(core, 'encrypt_file', interrupt)
    assert core.main(['encrypt', str(source), str(output), '--new-key-file', str(key)]) == 130
    assert str(key) in capsys.readouterr().err
    assert key.is_file() and not output.exists()


@pytest.mark.parametrize('size', [0, 11, core.IO_CHUNK + 37])
def test_change_after_final_read_callback_is_rejected(tmp_path, size):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'A' * size)
    before = source.stat()
    changed = []
    def progress(stage, done, total):
        if stage == 'read' and done == total == size and not changed:
            changed.append(True)
            source.write_bytes(b'B' * max(size, 1))
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(core.InputChangedError):
        core._build_plaintext(source, control=core.OperationControl(progress=progress))


def test_second_pass_can_cancel_without_replacing_output(sample, tmp_path):
    source, _, credential = sample
    output = tmp_path / 'old.saes'
    output.write_bytes(b'previous output')
    cancel = []
    def progress(stage, done, total):
        if stage == 'check_input' and done == core.IO_CHUNK:
            cancel.append(True)
    with pytest.raises(core.OperationCancelled):
        core.encrypt_file(source, output, credential=credential, force=True,
                          control=core.OperationControl(progress=progress, cancelled=lambda: bool(cancel)))
    assert output.read_bytes() == b'previous output'
    assert not list(tmp_path.glob('.moyle-*'))


def test_saes_body_reread_does_not_use_cached_bytes(sample, tmp_path):
    source, _, credential = sample
    source.write_bytes(b'small synthetic data')
    container = tmp_path / 'small.saes'
    core.encrypt_file(source, container, credential=credential)
    before = container.stat()
    changed = []
    def progress(stage, done, total):
        if stage == 'read' and done == total and not changed:
            changed.append(True)
            data = bytearray(container.read_bytes())
            data[-1] ^= 1
            container.write_bytes(data)
            os.utime(container, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(core.InputChangedError):
        core.decode_encrypted_file(container, credential=credential,
                                   control=core.OperationControl(progress=progress))


def test_stable_bounded_read_preserves_nonzero_offset_and_eof(tmp_path):
    source = tmp_path / 'offset.bin'
    source.write_bytes(b'header' + b'content' * 300)
    with source.open('rb', buffering=0) as handle:
        handle.seek(6)
        assert core._read_bounded(handle, 2100, core.OperationControl(), 'read') == b'content' * 300
        assert handle.tell() == source.stat().st_size and handle.read(1) == b''


def test_cancellation_while_preparing_key_permissions_does_not_publish_key(sample, tmp_path, monkeypatch):
    source, _, _ = sample
    key, output = tmp_path / 'cancel-permissions.stegkey', tmp_path / 'output.saes'
    def interrupt_permissions(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(Path, 'chmod', interrupt_permissions)
    assert core.main(['encrypt', str(source), str(output), '--new-key-file', str(key)]) == 130
    assert not key.exists() and not output.exists()
    assert not list(tmp_path.glob('.moyle-*'))
