"""GIF service routes, authenticated provenance and byte budgets use synthetic inputs."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from moyle_steg.service import OperationRequest, execute
from png_steg_aes256 import Credential, ContainerResourceLimitError, hide_file


@pytest.fixture
def gif_case(tmp_path):
    cover = tmp_path / 'cover.gif'
    frames = [Image.new('RGB', (12, 8), color) for color in ('red', 'blue', 'green')]
    frames[0].save(cover, save_all=True, append_images=frames[1:], duration=[40, 80, 120], loop=2, disposal=[1, 2, 3])
    source = tmp_path / 'synthetic.txt'
    source.write_bytes(b'GIF service synthetic payload\n' * 15)
    output = tmp_path / 'hidden.gif'
    return cover, source, output


def request(operation, cover, source, output='', **kwargs):
    return OperationRequest(operation=operation, cover_path=str(cover), input_path=str(source), output_path=str(output),
                            password='synthetic-service-password', password_confirm='synthetic-service-password', **kwargs)


def test_gif_preflight_and_hide_report_matching_format_frames_and_output(gif_case):
    cover, source, output = gif_case
    before = cover.read_bytes(), source.read_bytes()
    plan = execute(request('preflight', cover, source))
    assert plan.details['container_format'] == 'gif'
    assert plan.details['frame_count'] == '3'
    result = execute(request('hide', cover, source, output))
    assert result.details['container_format'] == 'gif'
    assert int(plan.details['output_bytes']) == output.stat().st_size
    assert (cover.read_bytes(), source.read_bytes()) == before


def test_gif_verify_uses_full_input_digest_and_writes_no_plaintext(gif_case):
    cover, source, output = gif_case
    execute(request('hide', cover, source, output))
    before = {p.name: p.read_bytes() for p in output.parent.iterdir()}
    result = execute(request('verify', '', output))
    assert result.details['container_format'] == 'gif'
    assert result.details['verified'] == 'yes'
    assert result.details['input_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result.details['payload_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.input_path == str(output.absolute())
    assert {p.name: p.read_bytes() for p in output.parent.iterdir()} == before


def test_gif_extract_restores_authenticated_original_filename(gif_case, tmp_path):
    cover, source, output = gif_case
    execute(request('hide', cover, source, output))
    destination = tmp_path / 'restore'
    result = execute(request('extract', '', output, output_directory=str(destination)))
    assert Path(result.output_path) == destination / source.name
    assert Path(result.output_path).read_bytes() == source.read_bytes()


@pytest.mark.parametrize('operation', ['extract', 'verify', 'inspect'])
def test_gif_recovery_container_budget_is_enforced(gif_case, tmp_path, operation):
    cover, source, output = gif_case
    hide_file(cover, source, output, credential=Credential.from_password('synthetic-service-password'))
    values = {'max_container_bytes': output.stat().st_size - 1}
    if operation == 'extract': values['output_directory'] = str(tmp_path / 'recover')
    with pytest.raises(ContainerResourceLimitError):
        execute(request(operation, '', output, **values))


def test_gif_capacity_page_does_not_claim_rgb_lsb_capacity(gif_case):
    cover, _, _ = gif_case
    result = execute(OperationRequest(operation='capacity', cover_path=str(cover)))
    assert result.details['container_format'] == 'gif'
    assert result.details['frame_count'] == '3'
    assert 'LSB' not in result.details['algorithm']

