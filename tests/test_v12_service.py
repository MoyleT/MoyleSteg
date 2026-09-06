"""Version 1.2 read-only verification and exact preflight contracts."""
from hashlib import sha256
from pathlib import Path
import pytest
from PIL import Image
from moyle_steg.service import OperationRequest, execute


def test_preflight_is_exact_readonly_and_needs_no_credentials(tmp_path):
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (80, 80), '#385b45').save(cover)
    source = tmp_path / 'document.txt'
    source.write_bytes(b'compressible payload' * 500)
    before = set(tmp_path.iterdir())
    result = execute(OperationRequest(operation='preflight', input_path=str(source), cover_path=str(cover)))
    assert result.operation == 'preflight'
    assert result.output_path == ''
    assert result.details['fits'] == 'yes'
    assert result.details['exact'] == 'yes'
    assert int(result.details['stored_size']) < source.stat().st_size
    assert int(result.details['ciphertext_bytes']) <= int(result.details['capacity'])
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize('container', ['png', 'saes'])
def test_verify_detects_format_by_signature_and_separates_checksums(tmp_path, container):
    source = tmp_path / 'payload.bin'
    source.write_bytes(b'payload integrity evidence' * 20)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (96, 96), '#64786a').save(cover)
    encoded = tmp_path / ('container.png' if container == 'png' else 'container.saes')
    execute(OperationRequest(operation='hide' if container == 'png' else 'encrypt',
        input_path=str(source), cover_path=str(cover), output_path=str(encoded),
        password='test credential', password_confirm='test credential'))
    encoded = encoded.rename(tmp_path / 'renamed.unrecognized-extension')
    before = set(tmp_path.iterdir())
    result = execute(OperationRequest(operation='verify', input_path=str(encoded), password='test credential'))
    assert result.output_path == ''
    assert result.details['container_format'] == container
    assert result.details['payload_sha256'] == sha256(source.read_bytes()).hexdigest()
    assert result.details['input_sha256'] == sha256(encoded.read_bytes()).hexdigest()
    assert result.details['payload_sha256'] != result.details['input_sha256']
    assert set(tmp_path.iterdir()) == before


def test_verify_rejects_input_growth_before_whole_file_hash(tmp_path):
    from png_steg_aes256 import OperationControl
    source = tmp_path / 'original.txt'
    source.write_bytes(b'bounded readonly verification')
    encoded = tmp_path / 'container.saes'
    execute(OperationRequest(operation='encrypt', input_path=str(source), output_path=str(encoded),
        password='test credential', password_confirm='test credential'))
    changed = []
    def mutate_at_input_hash(stage, completed, total):
        if stage == 'hash' and completed == 0 and total is not None and not changed:
            with encoded.open('ab') as stream:
                stream.write(b'unexpected growth')
            changed.append(True)
    with pytest.raises(ValueError) as caught:
        execute(OperationRequest(operation='verify', input_path=str(encoded), password='test credential'),
                control=OperationControl(progress=mutate_at_input_hash))
    assert getattr(caught.value, 'code', '') == 'input_changed'
    assert changed


def test_capacity_uses_core_pixel_policy(tmp_path):
    from png_steg_aes256 import StegError
    image = tmp_path / 'image.png'
    Image.new('RGB', (20, 20)).save(image)
    with pytest.raises(StegError):
        execute(OperationRequest(operation='capacity', cover_path=str(image), max_pixels=100))
