"""Synthetic desktop multi-file round trips and safe retry behavior."""
from pathlib import Path
import hashlib
import zipfile
import pytest
from PIL import Image
from moyle_steg.service import OperationRequest, execute
from png_steg_aes256 import Credential, decode_encrypted_file, OperationControl
from png_steg_aes256 import OperationCancelled, AuthenticationError, StegError
from moyle_steg.bundles import BundleSession
from moyle_bundle import BundleSource, create_bundle


def source_pair(tmp_path):
    first = tmp_path / 'a' / 'same.txt'
    second = tmp_path / 'b' / 'same.txt'
    first.parent.mkdir(); second.parent.mkdir()
    first.write_bytes(b'first synthetic content')
    second.write_bytes(b'second synthetic content')
    return first, second


def request(operation, **kw):
    return OperationRequest(operation, password='synthetic-test-only',
                            password_confirm='synthetic-test-only', **kw)


def test_multifile_authentication_lists_without_public_plaintext(tmp_path):
    sources = source_pair(tmp_path)
    output = tmp_path / 'files.saes'
    execute(request('encrypt', input_paths=tuple(map(str, sources)), output_path=str(output)))
    destination = tmp_path / 'restored'
    result = execute(request('decrypt', input_path=str(output), output_directory=str(destination),
                             detect_bundle=True))
    try:
        assert result.bundle is not None
        assert [e.name for e in result.bundle.info.entries] == ['same.txt', 'same.txt']
        assert not destination.exists()
    finally:
        if result.bundle:
            result.bundle.close()


def test_all_source_paths_protected_before_bundle_staging(tmp_path, monkeypatch):
    sources = source_pair(tmp_path)
    before = sources[1].read_bytes()
    with pytest.raises(ValueError):
        execute(request('encrypt', input_paths=tuple(map(str, sources)), output_path=str(sources[1]), force=True))
    assert sources[1].read_bytes() == before


def test_commit_progress_cannot_rebind_output_to_selected_source(tmp_path, monkeypatch):
    import moyle_steg.service as implementation
    sources = source_pair(tmp_path)
    destination = tmp_path / 'out.saes'
    def rebind(stage, completed, total):
        if stage == 'commit':
            # Model a newly observed filesystem alias. The test volume may be
            # exFAT, which cannot create real hard links.
            monkeypatch.setattr(implementation, '_same_path',
                                lambda left, right: left == destination and right == sources[1])
    with pytest.raises(ValueError):
        execute(request('encrypt', input_paths=tuple(map(str, sources)), output_path=str(destination), force=True),
                control=OperationControl(progress=rebind))
    assert not destination.exists()


def session_pair(tmp_path):
    sources = source_pair(tmp_path)
    archive = tmp_path / 'managed.zip'
    create_bundle([BundleSource(path, path.name) for path in sources], archive,
                  max_total_bytes=4096, max_archive_bytes=4096)
    session = BundleSession.from_authenticated(archive.read_bytes(), max_total_bytes=4096,
                      max_archive_bytes=4096, protected_paths=sources)
    return session, sources


def test_selected_then_all_uses_unique_names_and_retry_skips_saved(tmp_path):
    session, sources = session_pair(tmp_path)
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'same.txt').write_bytes(b'existing')
    try:
        session.save([2], output)
        first_saved = session.saved[2].path
        session.save([1, 2], output)
        assert Path(first_saved).read_bytes() == sources[1].read_bytes()
        assert Path(session.saved[1].path).read_bytes() == sources[0].read_bytes()
        assert {Path(value.path).name for value in session.saved.values()} == {'same (1).txt', 'same (2).txt'}
        assert (output / 'same.txt').read_bytes() == b'existing'
        session.save([1, 2], output)
        assert len(list(output.iterdir())) == 3
    finally:
        session.close()
    assert len(list(output.iterdir())) == 3
    assert not session.archive.exists()


def test_cancel_after_first_commit_keeps_it_and_retries_only_second(tmp_path):
    session, _ = session_pair(tmp_path)
    output = tmp_path / 'output'
    try:
        with pytest.raises(OperationCancelled):
            session.save([1, 2], output, control=OperationControl(cancelled=lambda: bool(session.saved)))
        assert list(session.saved) == [1]
        session.save([1, 2], output)
        assert len(session.saved) == 2
        assert len(list(output.iterdir())) == 2
    finally:
        session.close()


def test_publication_failure_retains_authenticated_session_for_retry(tmp_path, monkeypatch):
    import moyle_steg.bundles as implementation
    session, _ = session_pair(tmp_path)
    output = tmp_path / 'output'
    original_commit = implementation._commit_temp
    try:
        def fail(*args, **kwargs):
            raise PermissionError('synthetic denied')
        monkeypatch.setattr(implementation, '_commit_temp', fail)
        with pytest.raises(PermissionError):
            session.save([1], output)
        assert session.archive.is_file()
        assert session.saved == {}
        assert list(output.iterdir()) == []
        monkeypatch.setattr(implementation, '_commit_temp', original_commit)
        session.save([1], output)
        assert len(session.saved) == 1
    finally:
        session.close()


def test_disk_readback_tamper_never_publishes(tmp_path, monkeypatch):
    session, _ = session_pair(tmp_path)
    output = tmp_path / 'output'
    try:
        monkeypatch.setattr(session, '_digest', lambda *args: '0' * 64)
        with pytest.raises(StegError):
            session.save([1], output)
        assert session.saved == {}
        assert list(output.iterdir()) == []
    finally:
        session.close()


def test_competing_creator_is_never_replaced(tmp_path, monkeypatch):
    import moyle_steg.bundles as implementation
    session, _ = session_pair(tmp_path)
    output = tmp_path / 'output'
    original_commit = implementation._commit_temp
    try:
        def race(temporary, destination, **kwargs):
            destination.write_bytes(b'other process output')
            return original_commit(temporary, destination, **kwargs)
        monkeypatch.setattr(implementation, '_commit_temp', race)
        with pytest.raises(FileExistsError):
            session.save([1], output)
        assert (output / 'same.txt').read_bytes() == b'other process output'
        assert list(session.saved) == []
        monkeypatch.setattr(implementation, '_commit_temp', original_commit)
        session.save([1], output)
        assert Path(session.saved[1].path).name == 'same (1).txt'
    finally:
        session.close()


def test_save_whole_zip_is_explicit_and_valid_for_legacy_users(tmp_path):
    session, _ = session_pair(tmp_path)
    try:
        destination = session.save_archive(tmp_path / 'output')
        with zipfile.ZipFile(destination) as archive:
            assert archive.namelist() == ['0001/same.txt', '0002/same.txt']
        assert session.saved == {}
    finally:
        session.close()
    assert Path(destination).is_file()


def test_whole_zip_rejects_metadata_change_with_unchanged_members(tmp_path):
    session, _ = session_pair(tmp_path)
    try:
        data = bytearray(session.archive.read_bytes())
        # DOS timestamp is not member content, size, CRC or SHA-256. Changing
        # matching local/central fields preserves an otherwise valid archive.
        cursor = 0
        while (cursor := data.find(b'PK\x03\x04', cursor)) >= 0:
            data[cursor + 10] ^= 1
            cursor += 4
        cursor = 0
        while (cursor := data.find(b'PK\x01\x02', cursor)) >= 0:
            data[cursor + 12] ^= 1
            cursor += 4
        session.archive.write_bytes(data)
        with pytest.raises(StegError):
            session.save_archive(tmp_path / 'output')
        assert not (tmp_path / 'output').exists()
    finally:
        session.close()


@pytest.mark.parametrize('operation', ['encrypt', 'hide'])
def test_existing_decoders_restore_bundle_zip_without_format_change(tmp_path, operation):
    from png_steg_aes256 import decode_image
    sources = source_pair(tmp_path)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (200, 200), '#235480').save(cover)
    output = tmp_path / ('hidden.png' if operation == 'hide' else 'encrypted.saes')
    execute(request(operation, input_paths=tuple(map(str, sources)), output_path=str(output), cover_path=str(cover)))
    decoder = decode_image if operation == 'hide' else decode_encrypted_file
    decoded = decoder(output, credential=Credential.from_password('synthetic-test-only'))
    assert decoded.filename == 'MoyleSteg-files.zip'
    assert decoded.data.endswith(b'MOYLESTEG-BUNDLE-V1')


def test_ordinary_zip_stays_single_file(tmp_path):
    archive = tmp_path / 'ordinary.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('nested/plain.txt', b'ordinary user archive')
    encrypted = tmp_path / 'ordinary.saes'
    execute(request('encrypt', input_paths=(str(archive),), output_path=str(encrypted)))
    result = execute(request('decrypt', input_path=str(encrypted), output_directory=str(tmp_path / 'output'), detect_bundle=True))
    assert result.bundle is None
    assert Path(result.output_path).read_bytes() == archive.read_bytes()


def test_wrong_password_creates_no_bundle_staging(tmp_path, monkeypatch):
    sources = source_pair(tmp_path)
    encrypted = tmp_path / 'files.saes'
    execute(request('encrypt', input_paths=tuple(map(str, sources)), output_path=str(encrypted)))
    def unexpected(*args, **kwargs):
        pytest.fail('Unauthenticated data reached bundle handling')
    monkeypatch.setattr(BundleSession, 'from_authenticated', unexpected)
    with pytest.raises(AuthenticationError):
        execute(OperationRequest('decrypt', input_path=str(encrypted), output_directory=str(tmp_path / 'output'),
                                 detect_bundle=True, password='incorrect'))
    assert not (tmp_path / 'output').exists()


def test_preflight_packs_actual_total_without_output(tmp_path):
    sources = source_pair(tmp_path)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (200, 200), '#235480').save(cover)
    result = execute(OperationRequest('preflight', input_paths=tuple(map(str, sources)), cover_path=str(cover)))
    assert result.details['file_count'] == '2'
    assert int(result.details['source_total_bytes']) == sum(path.stat().st_size for path in sources)
    assert int(result.details['original_size']) == int(result.details['bundle_bytes'])
    assert result.output_path == ''


def test_verify_never_stages_plaintext_bundle(tmp_path, monkeypatch):
    sources = source_pair(tmp_path)
    encrypted = tmp_path / 'files.saes'
    execute(request('encrypt', input_paths=tuple(map(str, sources)), output_path=str(encrypted)))
    def unexpected(*args, **kwargs):
        pytest.fail('Read-only verification staged a plaintext bundle')
    monkeypatch.setattr(BundleSession, 'from_authenticated', unexpected)
    result = execute(request('verify', input_path=str(encrypted), detect_bundle=True))
    assert result.bundle is None
    assert result.details['verified'] == 'yes'
