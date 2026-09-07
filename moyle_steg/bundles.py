"""Private authenticated multi-file session and non-overwriting publication.

The session owns only its randomly created temporary directory. Public files are
never removed on cancellation, retry, result invalidation or session cleanup.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
from threading import RLock
import hashlib
import os

from moyle_bundle import inspect_bundle, extract_entry, BundleInfo
from png_steg_aes256 import OperationControl, StegError, _commit_temp, validate_operation_paths, _same_path


@dataclass(frozen=True)
class SavedMember:
    index: int
    path: str
    sha256: str


class BundleSession:
    def __init__(self, temporary, archive, info, *, archive_sha256, max_total_bytes, max_archive_bytes, protected_paths):
        self._temporary = temporary
        self.archive = archive
        self.info: BundleInfo = info
        self.archive_sha256 = archive_sha256
        self.max_total_bytes = max_total_bytes
        self.max_archive_bytes = max_archive_bytes
        self.protected_paths = tuple(protected_paths)
        self.saved: dict[int, SavedMember] = {}
        self.archive_saved: str = ""
        self.closed = False
        self._lock = RLock()

    @classmethod
    def from_authenticated(cls, data, *, max_total_bytes, max_archive_bytes, protected_paths=(), control=None):
        # Arbitrary user ZIPs must remain a single file. Probe only the exact
        # authenticated marker before any plaintext staging or ZIP interpretation.
        if not data.endswith(b'MOYLESTEG-BUNDLE-V1'):
            return None
        control = control or OperationControl()
        if len(data) > max_archive_bytes:
            raise StegError('文件超过处理资源上限')
        temporary = TemporaryDirectory(prefix='moyle-bundle-restore-')
        archive = Path(temporary.name) / 'MoyleSteg-files.zip'
        try:
            with archive.open('xb') as stream:
                for offset in range(0, len(data), 65536):
                    control.check()
                    stream.write(data[offset:offset + 65536])
                    control.report('bundle', min(offset + 65536, len(data)), len(data))
            archive_sha256 = hashlib.sha256(data).hexdigest()
            if cls._digest(archive, len(data), control) != archive_sha256:
                raise StegError('私有恢复副本摘要不一致')
            info = inspect_bundle(archive, max_total_bytes=max_total_bytes,
                                  max_archive_bytes=max_archive_bytes, control=control)
            if info is None:
                temporary.cleanup()
                return None
            return cls(temporary, archive, info, archive_sha256=archive_sha256, max_total_bytes=max_total_bytes,
                       max_archive_bytes=max_archive_bytes, protected_paths=protected_paths)
        except BaseException:
            temporary.cleanup()
            raise

    def _check(self):
        if self.closed:
            raise StegError('恢复会话已清理，请重新认证文件')

    def close(self):
        with self._lock:
            if not self.closed:
                self.closed = True
                self._temporary.cleanup()

    def save(self, indices, directory, *, control=None):
        control = control or OperationControl()
        with self._lock:
            self._check()
            indices = tuple(dict.fromkeys(indices))
            by_index = {entry.index: entry for entry in self.info.entries}
            if not indices or any(index not in by_index for index in indices):
                raise ValueError('请选择有效的文件')
            directory = self._directory(directory)
            for index in indices:
                if index in self.saved:
                    continue
                control.check()
                entry = by_index[index]
                temporary = extract_entry(self.archive, entry, Path(self._temporary.name),
                                  max_total_bytes=self.max_total_bytes,
                                  max_archive_bytes=self.max_archive_bytes, control=control)
                try:
                    destination = self._publish(temporary, entry.name, directory, entry.size, entry.sha256, control)
                    # No cancellation checkpoint between commit and recording it.
                    self.saved[index] = SavedMember(index, str(destination), entry.sha256)
                finally:
                    temporary.unlink(missing_ok=True)
            return tuple(self.saved.values())

    def save_archive(self, directory, *, control=None):
        control = control or OperationControl()
        with self._lock:
            self._check()
            if self.archive_saved:
                return self.archive_saved
            info = inspect_bundle(self.archive, max_total_bytes=self.max_total_bytes,
                                  max_archive_bytes=self.max_archive_bytes, control=control)
            if info != self.info:
                raise StegError('私有恢复副本发生变化')
            if self._digest(self.archive, self.info.archive_bytes, control) != self.archive_sha256:
                raise StegError('私有恢复副本发生变化')
            destination = self._publish(self.archive, 'MoyleSteg-files.zip', self._directory(directory),
                                        self.info.archive_bytes, self.archive_sha256, control)
            self.archive_saved = str(destination)
            return self.archive_saved

    def _directory(self, value):
        directory = Path(value)
        if not directory.is_absolute():
            raise ValueError('恢复目录必须是绝对路径')
        directory = directory.resolve()
        if directory.exists() and not directory.is_dir():
            raise NotADirectoryError('恢复目录不是文件夹')
        return directory

    @staticmethod
    def _digest(path, expected_size, control):
        digest, completed = hashlib.sha256(), 0
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                control.check()
                completed += len(chunk)
                if completed > expected_size:
                    raise StegError('恢复副本大小不一致')
                digest.update(chunk)
        if completed != expected_size:
            raise StegError('恢复副本大小不一致')
        return digest.hexdigest()

    def _publish(self, source, name, directory, expected_size, expected_hash, control):
        # Validate all candidates before directory or temporary output creation.
        protected = self.protected_paths + (self.archive,)
        stem, suffix = Path(name).stem, Path(name).suffix
        destination = None
        for number in range(10000):
            label = name if number == 0 else f'{stem} ({number}){suffix}'
            candidate = directory / label
            if candidate.resolve(strict=False).parent != directory:
                continue
            if any(_same_path(candidate, path) for path in protected):
                continue
            try:
                validate_operation_paths(inputs=protected, output=candidate)
            except FileExistsError:
                continue
            destination = candidate
            break
        if destination is None:
            raise FileExistsError('无法分配唯一文件名')
        control.check()
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = mkstemp(prefix='.moyle-', suffix='.tmp', dir=directory)
        temporary = Path(temporary_name)
        try:
            count, digest = 0, hashlib.sha256()
            with source.open('rb') as incoming, os.fdopen(fd, 'wb') as outgoing:
                fd = None
                while chunk := incoming.read(65536):
                    control.check()
                    count += len(chunk)
                    if count > expected_size:
                        raise StegError('恢复副本大小不一致')
                    digest.update(chunk)
                    outgoing.write(chunk)
                    control.report('save', count, expected_size)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if count != expected_size or digest.hexdigest() != expected_hash:
                raise StegError('恢复副本摘要不一致')
            if self._digest(temporary, expected_size, control) != expected_hash:
                raise StegError('保存后回读摘要不一致')
            # A concurrent creator can win after filename selection. Refuse
            # replacement and let the retained authenticated session retry.
            _commit_temp(temporary, destination, protected_paths=protected, control=control)
            return destination
        finally:
            if fd is not None:
                os.close(fd)
            temporary.unlink(missing_ok=True)
