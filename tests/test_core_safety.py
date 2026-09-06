"""Synthetic reproductions of file-safety and resource-boundary findings."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
import png_steg_aes256 as core


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / '原文.txt'
    source.write_bytes(b'original payload' * 100)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (128, 96), '#247b68').save(cover)
    key = tmp_path / 'key.stegkey'
    core.generate_key_file(key)
    return source, cover, key


@pytest.mark.parametrize('command', ['encrypt', 'hide'])
@pytest.mark.parametrize('collision', ['source', 'cover', 'output'])
def test_cli_new_key_collisions_rejected_before_any_write(sample, tmp_path, command, collision):
    source, cover, key = sample
    output = tmp_path / ('result.png' if command == 'hide' else 'result.saes')
    target = {'source': source, 'cover': cover, 'output': output}[collision]
    if command == 'encrypt' and collision == 'cover':
        target = source
    before = {p: p.read_bytes() for p in (source, cover, key)}
    args = [command] + ([str(cover), str(source)] if command == 'hide' else [str(source)])
    args += [str(output), '--new-key-file', str(target), '--force-key', '--force']
    assert core.main(args) == 2
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not output.exists()


@pytest.mark.parametrize('command', ['encrypt', 'hide'])
def test_direct_core_cannot_replace_credential_file_even_with_force(sample, command):
    source, cover, key = sample
    if command == 'hide':
        renamed = key.with_suffix('.png')
        key.rename(renamed)
        key = renamed
    before = key.read_bytes()
    credential = core.Credential.from_key_file(key)
    with pytest.raises(ValueError):
        if command == 'hide':
            core.hide_file(cover, source, key, credential=credential, force=True)
        else:
            core.encrypt_file(source, key, credential=credential, force=True)
    assert key.read_bytes() == before


def test_atomic_write_never_replaces_existing_without_force(tmp_path):
    target = tmp_path / 'output'
    target.write_bytes(b'winner')
    with pytest.raises(FileExistsError):
        core._atomic_write(target, b'loser')
    assert target.read_bytes() == b'winner'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['output']


def test_pixel_limit_precedes_payload_read_and_conversion(sample, tmp_path, monkeypatch):
    source, cover, _ = sample
    def forbidden(*args, **kwargs):
        pytest.fail('expensive processing preceded header resource check')
    monkeypatch.setattr(core, '_build_plaintext', forbidden)
    monkeypatch.setattr(Image.Image, 'convert', forbidden)
    with pytest.raises(core.StegError):
        core.hide_file(cover, source, tmp_path / 'out.png',
                       credential=core.Credential.from_password('test'), max_pixels=1024)


def test_saved_saes_is_reread_before_commit(sample, tmp_path, monkeypatch):
    source, _, key = sample
    real_fsync = core.os.fsync
    def corrupt_saved_bytes(fd):
        real_fsync(fd)
        # Modify the same temporary file after its write/flush, before readback.
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, core.HEADER_SIZE + 2, os.SEEK_SET)
        os.write(fd, b'\xff' * 8)
        os.lseek(fd, pos, os.SEEK_SET)
    monkeypatch.setattr(core.os, 'fsync', corrupt_saved_bytes)
    target = tmp_path / 'out.saes'
    with pytest.raises(core.AuthenticationError):
        core.encrypt_file(source, target, credential=core.Credential.from_key_file(key))
    assert not target.exists()
    assert not list(tmp_path.glob('out.saes.*.tmp'))


def test_cover_orientation_applied_before_embedding_without_exif(sample, tmp_path):
    source, _, key = sample
    cover = tmp_path / 'oriented.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (80, 40), '#abcdef').save(cover, exif=exif)
    output = tmp_path / 'out.png'
    credential = core.Credential.from_key_file(key)
    core.hide_file(cover, source, output, credential=credential)
    with Image.open(output) as image:
        assert image.size == (40, 80)
        assert not image.getexif()
    assert core.decode_image(output, credential=credential).data == source.read_bytes()


@pytest.mark.parametrize('name', ['C:relative.txt', 'file.txt:stream', 'CON.txt', 'COM¹.txt',
                                  'LPT9', 'file.', 'file ', 'aux .log', 'a\x1fb'])
def test_core_rejects_windows_unsafe_metadata(name):
    with pytest.raises(core.StegError):
        core._safe_filename(name)


def test_two_independent_cli_processes_only_one_wins(tmp_path):
    sources = [tmp_path / f'source{i}.bin' for i in range(2)]
    for source in sources:
        source.write_bytes(os.urandom(8 * 1024 * 1024))
    target = tmp_path / 'shared.saes'
    script = str(Path(core.__file__).resolve())
    processes = [subprocess.Popen([sys.executable, script, 'encrypt', str(source), str(target),
                                    '--password', 'synthetic-race-test'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for source in sources]
    for process in processes:
        process.communicate(timeout=60)
    assert sorted(p.returncode for p in processes) == [0, 2]
    decoded = core.decode_encrypted_file(target, credential=core.Credential.from_password('synthetic-race-test'))
    winner = next(i for i, p in enumerate(processes) if p.returncode == 0)
    assert decoded.data == sources[winner].read_bytes()


def test_cli_existing_key_cannot_be_output(sample):
    source, _, key = sample
    before = key.read_bytes()
    assert core.main(['encrypt', str(source), str(key), '--key-file', str(key), '--force']) == 2
    assert key.read_bytes() == before


@pytest.mark.parametrize('auto_name', [False, True])
def test_restoration_cannot_replace_credential_even_with_force(sample, tmp_path, monkeypatch, auto_name):
    _, _, key = sample
    payload_dir = tmp_path / 'payload'
    payload_dir.mkdir()
    source = payload_dir / key.name
    source.write_bytes(b'payload whose original name collides with credential')
    credential = core.Credential.from_key_file(key)
    container = tmp_path / 'out.saes'
    core.encrypt_file(source, container, credential=credential)
    before = key.read_bytes()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        core.decrypt_encrypted_file(container, None if auto_name else key, credential=credential, force=True)
    assert key.read_bytes() == before


def test_source_alias_is_protected(sample, tmp_path, monkeypatch):
    source, _, key = sample
    # Test identity branch independently of exFAT's lack of hardlink support.
    alias = tmp_path / 'alias'
    actual_samefile = core.os.path.samefile
    monkeypatch.setattr(core.os.path, 'samefile',
                        lambda left, right: True if {Path(left), Path(right)} == {source, alias}
                        else actual_samefile(left, right))
    with pytest.raises(ValueError):
        core.encrypt_file(source, alias, credential=core.Credential.from_key_file(key), force=True)
    assert not alias.exists()


@pytest.mark.parametrize('key_is_parent', [False, True])
def test_new_key_and_output_cannot_be_parent_and_child(sample, tmp_path, key_is_parent):
    source, _, _ = sample
    parent = tmp_path / 'not-created.saes'
    child = parent / 'child.saes'
    key, output = (parent, child) if key_is_parent else (child, parent)
    assert core.main(['encrypt', str(source), str(output), '--new-key-file', str(key), '--force']) == 2
    assert not parent.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows drive-relative path semantics')
def test_drive_relative_write_rejected_at_public_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = Path(tmp_path.drive + 'drive-relative.stegkey')
    assert not output.is_absolute()
    with pytest.raises(ValueError):
        core.generate_key_file(output)
    assert not (tmp_path / 'drive-relative.stegkey').exists()
    with pytest.raises(ValueError):
        core.generate_key_file(Path('\\root-relative.stegkey'))
    key = core.generate_key_file(Path('ordinary-relative.stegkey'))
    assert core.read_key_file(tmp_path / 'ordinary-relative.stegkey') == key
