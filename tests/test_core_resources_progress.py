"""Resource budgets precede allocations; cancellation never publishes partial data."""
import os
from pathlib import Path
import pytest
from PIL import Image
import png_steg_aes256 as core


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / 'payload.txt'
    source.write_bytes(b'compressible payload\n' * 1000)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (64, 64), '#446677').save(cover)
    return source, cover, core.Credential.from_password('synthetic budget test')


@pytest.mark.parametrize('operation', ['hide', 'encrypt'])
def test_payload_limit_rejects_before_read(inputs, tmp_path, monkeypatch, operation):
    source, cover, credential = inputs
    original = core._read_bounded
    calls = []
    def checked(handle, limit, control, stage):
        calls.append(os.fstat(handle.fileno()).st_size)
        return original(handle, limit, control, stage)
    monkeypatch.setattr(core, '_read_bounded', checked)
    def forbidden(*args, **kwargs):
        pytest.fail('compression ran before file resource rejection')
    monkeypatch.setattr(core.zlib, 'compressobj', forbidden)
    with pytest.raises(core.StegError, match='资源上限'):
        if operation == 'hide':
            core.hide_file(cover, source, tmp_path / 'out.png', credential=credential, max_file_bytes=10)
        else:
            core.encrypt_file(source, tmp_path / 'out.saes', credential=credential, max_file_bytes=10)
    assert calls == [source.stat().st_size]


@pytest.mark.parametrize('entry', ['decode_image', 'peek_header', 'extract_file'])
def test_decode_budget_checked_before_conversion(inputs, tmp_path, monkeypatch, entry):
    source, cover, credential = inputs
    def forbidden(*args, **kwargs):
        pytest.fail('pixel conversion ran before resource check')
    monkeypatch.setattr(Image.Image, 'convert', forbidden)
    with pytest.raises(core.StegError, match='像素数超过'):
        if entry == 'peek_header':
            core.peek_header(cover, max_pixels=1024)
        elif entry == 'extract_file':
            core.extract_file(cover, tmp_path / 'restored', credential=credential, max_pixels=1024)
        else:
            core.decode_image(cover, credential=credential, max_pixels=1024)


def test_saes_declared_or_actual_size_checked_before_body_read(inputs, tmp_path, monkeypatch):
    _, _, credential = inputs
    container = tmp_path / 'bad.saes'
    header = core._build_header(credential.mode, b's' * 16, b'n' * 12, 1000000)
    container.write_bytes(core._serialize_header(header))
    monkeypatch.setattr(core, '_read_bounded', lambda *a, **k: pytest.fail('body read before header/length check'))
    with pytest.raises(core.StegError):
        core.decode_encrypted_file(container, credential=credential, max_file_bytes=1024)


def test_compressed_original_budget_before_decompression(inputs, tmp_path, monkeypatch):
    source, _, credential = inputs
    encrypted = tmp_path / 'out.saes'
    core.encrypt_file(source, encrypted, credential=credential)
    monkeypatch.setattr(core.zlib, 'decompressobj', lambda *a, **k: pytest.fail('decompressed before budget'))
    with pytest.raises(core.StegError, match='原始文件过大'):
        core.decode_encrypted_file(encrypted, credential=credential, max_file_bytes=1024)


@pytest.mark.parametrize('stage', ['read', 'compress', 'encrypt', 'save', 'verify.read', 'commit'])
def test_cancel_standalone_preserves_existing_destination(inputs, tmp_path, stage):
    source, _, credential = inputs
    target = tmp_path / 'existing.saes'
    target.write_bytes(b'previous output')
    state = {'cancelled': False}
    seen = []
    def progress(name, done, total):
        seen.append(name)
        if name == stage:
            state['cancelled'] = True
    control = core.OperationControl(progress, lambda: state['cancelled'])
    with pytest.raises(core.OperationCancelled):
        core.encrypt_file(source, target, credential=credential, force=True, control=control)
    assert stage in seen
    assert target.read_bytes() == b'previous output'
    assert not list(tmp_path.glob('.moyle-*'))


@pytest.mark.parametrize('stage', ['image', 'embed', 'save', 'verify.image', 'verify.extract', 'commit'])
def test_cancel_png_never_publishes_partial_output(inputs, tmp_path, stage):
    source, cover, credential = inputs
    target = tmp_path / 'out.png'
    state = []
    control = core.OperationControl(lambda name, done, total: state.append(name), lambda: stage in state)
    with pytest.raises(core.OperationCancelled):
        core.hide_file(cover, source, target, credential=credential, control=control)
    assert not target.exists()
    assert not list(tmp_path.glob('.moyle-*'))


def test_preflight_exact_sizes_match_output_and_makes_no_files(inputs, tmp_path):
    source, cover, credential = inputs
    before = set(tmp_path.iterdir())
    plan = core.preflight_hide(cover, source, auto_resize=True, max_fill=.5)
    assert set(tmp_path.iterdir()) == before
    result = core.hide_file(cover, source, tmp_path / 'out.png', credential=credential,
                            auto_resize=True, max_fill=.5)
    assert plan.exact and plan.fits
    assert plan.ciphertext_bytes == result.ciphertext_bytes
    assert plan.stored_size == result.stored_size
    assert (plan.image_width, plan.image_height) == (result.image_width, result.image_height)
    assert plan.fill_ratio == result.fill_ratio
    assert plan.estimated_peak_bytes > plan.image_width * plan.image_height * 4


def test_preflight_reports_unfit_without_allocating_larger_raster(inputs, monkeypatch):
    source, cover, _ = inputs
    source.write_bytes(os.urandom(3000))
    monkeypatch.setattr(Image.Image, 'resize', lambda *a, **k: pytest.fail('preflight expanded raster'))
    plan = core.preflight_hide(cover, source, auto_resize=True, max_fill=.5, max_pixels=4096)
    assert not plan.fits and plan.reason == 'pixels'
    assert plan.image_width * plan.image_height > 4096


def test_rounded_resize_rejected_before_allocation(monkeypatch):
    image = Image.new('RGB', (10, 1))
    monkeypatch.setattr(Image.Image, 'convert', lambda *a, **k: pytest.fail('allocation before rounded check'))
    length = 10
    rounded = core._payload_dimensions(image.size, length, 1.0)
    theoretical = (core.HEADER_BITS + length * 8 + 2) // 3
    assert rounded[0] * rounded[1] > theoretical
    with pytest.raises(core.StegError):
        core._resize_for_payload(image, length, max_fill=1.0, max_pixels=theoretical)


def test_destination_appearing_at_commit_is_never_overwritten(tmp_path, monkeypatch):
    target = tmp_path / 'race'
    primitive = 'rename' if os.name == 'nt' else 'link'
    original = getattr(core.os, primitive)
    def concurrent_create(src, dst):
        Path(dst).write_bytes(b'other instance')
        return original(src, dst)
    monkeypatch.setattr(core.os, primitive, concurrent_create)
    with pytest.raises(FileExistsError):
        core._atomic_write(target, b'ours')
    assert target.read_bytes() == b'other instance'
    assert set(tmp_path.iterdir()) == {target}
