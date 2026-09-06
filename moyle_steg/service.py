"""Qt-independent service boundary for desktop steganography operations.

This module deliberately returns display-neutral strings.  The window translates
result titles and detail labels, while :func:`friendly_error` is the only place
where user-facing failure text is selected.
"""

from __future__ import annotations

import os
import hashlib
import errno
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

from PIL import Image, UnidentifiedImageError

from png_steg_aes256 import (
    AuthenticationError,
    OperationControl,
    OperationCancelled,
    DEFAULT_MAX_PIXELS,
    DEFAULT_MAX_FILE_BYTES,
    MAGIC,
    Credential,
    DecodedPayload,
    EncryptResult,
    HideResult,
    MODE_KEY_FILE,
    MODE_PASSWORD,
    StegError,
    _atomic_write,
    _checked_container_header,
    _check_container_budget,
    _check_pixels,
    _validate_limits,
    _safe_filename,
    _same_path as _core_same_path,
    decode_encrypted_file,
    decode_image,
    decrypt_encrypted_file,
    encrypt_file,
    extract_file,
    generate_key_file,
    hide_file,
    image_capacity_bytes,
    preflight_hide,
    cover_dimensions,
    gif_cover_info,
    validate_operation_paths,
)


_OPERATIONS = {"hide", "extract", "inspect", "verify", "preflight", "encrypt", "decrypt", "keygen", "capacity"}
_WRITE_OPERATIONS = {"hide", "extract", "encrypt", "decrypt", "keygen"}
_PASSWORD_WRITE_OPERATIONS = {"hide", "encrypt"}
_RECOVERY_OPERATIONS = {"extract", "decrypt", "inspect", "verify"}
DEFAULT_MAX_CONTAINER_BYTES = 512 * 1024 * 1024
TEMPORARY_RESERVE_BYTES = 16 * 1024 * 1024


class _ValidationError(ValueError):
    """Validation failure carrying a stable localization code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _ResourceLimitError(StegError):
    def __init__(self, code: str) -> None:
        super().__init__("文件超过处理资源上限")
        self.code = code


class _TemporarySpaceError(OSError):
    code = "temporary_space"

    def __init__(self) -> None:
        super().__init__(errno.ENOSPC, "临时磁盘可用空间不足")


@dataclass(frozen=True)
class RecoveryResources:
    """Metadata-only estimate; free space can change before capture starts.

    ``temporary_required`` includes the 16 MiB reserve, and is zero when the
    selected operation does not capture a private encrypted container copy.
    """

    input_size: int
    temporary_required: int
    temporary_free: int
    temporary_directory: str


def probe_recovery_resources(input_path: str | Path, *, operation: str = "verify") -> RecoveryResources:
    """Inspect size and temporary-volume free space without reading file bytes."""
    if operation not in _RECOVERY_OPERATIONS:
        raise _ValidationError("unknown_operation", "不支持的恢复操作")
    path = _required_input(str(input_path), "input")
    return _recovery_resources(path.stat().st_size, operation)


def _recovery_resources(input_size: int, operation: str) -> RecoveryResources:
    temporary_directory = gettempdir()
    free = shutil.disk_usage(temporary_directory).free
    required = input_size + TEMPORARY_RESERVE_BYTES if operation in {"inspect", "verify"} else 0
    return RecoveryResources(input_size, required, free, temporary_directory)


@dataclass
class OperationRequest:
    operation: str
    input_path: str = ""
    output_path: str = ""
    cover_path: str = ""
    credential_mode: str = "password"
    password: str = field(default="", repr=False)
    password_confirm: str = field(default="", repr=False)
    key_path: str = ""
    auto_resize: bool = False
    max_fill: float = 0.75
    max_pixels: int = DEFAULT_MAX_PIXELS
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    force: bool = False
    output_directory: str = ""
    max_container_bytes: int = DEFAULT_MAX_CONTAINER_BYTES

    def __repr__(self) -> str:
        return (
            f"OperationRequest(operation={self.operation!r}, input_path={self.input_path!r}, "
            f"output_path={self.output_path!r}, cover_path={self.cover_path!r}, "
            f"credential_mode={self.credential_mode!r}, password=<hidden>, "
            f"password_confirm=<hidden>, key_path={self.key_path!r}, "
            f"auto_resize={self.auto_resize!r}, max_fill={self.max_fill!r}, "
            f"max_pixels={self.max_pixels!r}, force={self.force!r}, "
            f"max_file_bytes={self.max_file_bytes!r}, "
            f"max_container_bytes={self.max_container_bytes!r}, "
            f"output_directory={self.output_directory!r})"
        )


@dataclass(frozen=True)
class OperationResult:
    operation: str
    output_path: str = ""
    title: str = ""
    details: dict[str, str] = field(default_factory=dict)
    input_path: str = ""
    completed_at: str = ""


def execute(request: OperationRequest, *, control: OperationControl | None = None) -> OperationResult:
    """Execute a captured request and bind its result to the selected input."""
    if not isinstance(request, OperationRequest):
        raise TypeError("request 必须为 OperationRequest")
    # Progress callbacks and GUI edits must not change the task's provenance.
    request = replace(request)
    for name in ("input_path", "cover_path"):
        if value := getattr(request, name):
            setattr(request, name, str(Path(value).absolute()))
    context_input = (request.cover_path or request.input_path) if request.operation == "capacity" else request.input_path
    try:
        result = _execute(request, control=control)
    except StegError as exc:
        raw = str(exc)
        if not getattr(exc, "code", "") and any(marker in raw for marker in ("资源上限", "安全解码上限", "像素数超过")):
            code = "recovery_resource_limit" if request.operation in _RECOVERY_OPERATIONS else "source_resource_limit"
            raise _ResourceLimitError(code) from exc
        raise
    except OSError as exc:
        if request.operation in {"inspect", "verify"} and (exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in {39, 112}):
            if isinstance(exc, _TemporarySpaceError):
                raise
            raise _TemporarySpaceError() from exc
        raise
    return replace(result, input_path=context_input,
                   completed_at=datetime.now().astimezone().isoformat(timespec="seconds"))


def _execute(request: OperationRequest, *, control: OperationControl | None = None) -> OperationResult:
    """Validate and synchronously execute one desktop operation.

    Expected failures are allowed to propagate so the background worker can
    pass them through :func:`friendly_error`.  Every path check that can prevent
    a write runs before a core write function is called.
    """

    if not isinstance(request, OperationRequest):
        raise TypeError("request 必须为 OperationRequest")
    control = control or OperationControl()
    control.check()
    operation = request.operation
    if operation not in _OPERATIONS:
        raise _ValidationError("unknown_operation", "不支持的操作")

    output_directory = (
        _validate_output_directory(request) if request.output_directory else None
    )
    output_path = (
        _validate_output(request)
        if operation in _WRITE_OPERATIONS and output_directory is None
        else None
    )

    if operation == "keygen":
        assert output_path is not None
        generate_key_file(output_path, force=request.force, control=control)
        return OperationResult(
            operation=operation,
            output_path=str(output_path),
            title="keygen_success",
            details={"credential_mode": "key_file", "algorithm": "256-bit random key"},
        )

    if operation == "capacity":
        image_path = _required_input(request.cover_path or request.input_path, "image")
        control.report("image")
        with image_path.open('rb') as stream:
            gif = stream.read(6) in (b'GIF87a', b'GIF89a')
        if gif:
            info = gif_cover_info(image_path, max_pixels=request.max_pixels,
                                  max_container_bytes=request.max_container_bytes, control=control)
            return OperationResult(operation=operation, title="capacity_success", details={
                "width": str(info.width), "height": str(info.height), "frame_count": str(info.frame_count),
                "container_format": "gif", "algorithm": "GIF application extension",
            })
        width, height = cover_dimensions(image_path, max_pixels=request.max_pixels)
        control.report("image", 1, 1)
        return OperationResult(
            operation=operation,
            title="capacity_success",
            details={
                "width": str(width),
                "height": str(height),
                "capacity": str(image_capacity_bytes(width, height)),
                "algorithm": "RGB 1-LSB",
            },
        )

    input_path = _required_input(request.input_path, "input")
    if operation in _RECOVERY_OPERATIONS:
        _check_container_budget(input_path.stat().st_size, request.max_container_bytes)
    cover_path = _required_input(request.cover_path, "cover") if operation in {"hide", "preflight"} else None
    if operation == "preflight":
        result = preflight_hide(cover_path, input_path, auto_resize=request.auto_resize,
            max_fill=request.max_fill, max_pixels=request.max_pixels,
            max_file_bytes=request.max_file_bytes, max_container_bytes=request.max_container_bytes, control=control)
        return OperationResult(operation=operation, title="preflight_success", details={
            "original_size": str(result.original_size), "stored_size": str(result.stored_size),
            "compressed": _bool_name(result.compressed), "ciphertext_bytes": str(result.ciphertext_bytes),
            "capacity": str(result.capacity_bytes), "width": str(result.image_width),
            "height": str(result.image_height), "fill_ratio": str(result.fill_ratio),
            "fits": _bool_name(result.fits), "exact": _bool_name(result.exact),
            "estimated_peak_bytes": str(result.estimated_peak_bytes),
            "resource_level": result.resource_level, "reason": result.reason,
            "container_format": result.container_format, "frame_count": str(result.frame_count),
            "output_bytes": str(result.output_bytes),
        })
    credential = _credential(request, for_write=operation in _PASSWORD_WRITE_OPERATIONS)

    if operation in {"inspect", "verify"}:
        return _verify(request, input_path, credential, control)

    if output_directory is not None:
        decoded = (
            decode_image(input_path, credential=credential, max_pixels=request.max_pixels,
                         max_file_bytes=request.max_file_bytes,
                         max_container_bytes=request.max_container_bytes, control=control)
            if operation == "extract"
            else decode_encrypted_file(input_path, credential=credential,
                                       max_file_bytes=request.max_file_bytes,
                                       max_container_bytes=request.max_container_bytes, control=control)
        )
        destination = _original_destination(request, output_directory, decoded.filename)
        # Authentication and every destination check precede directory creation.
        # The original core helper creates parents and atomically saves the data.
        _atomic_write(destination, decoded.data, force=request.force,
                      protected_paths=tuple(Path(value) for value in (request.input_path, request.cover_path, request.key_path) if value),
                      control=control)
        return OperationResult(
            operation=operation,
            output_path=str(destination),
            title=f"{operation}_success",
            details=_decoded_details(decoded),
        )

    if operation == "hide":
        assert cover_path is not None and output_path is not None
        core_result = hide_file(
            cover_path,
            input_path,
            output_path,
            credential=credential,
            auto_resize=request.auto_resize,
            max_fill=request.max_fill,
            max_pixels=request.max_pixels,
            max_file_bytes=request.max_file_bytes,
            max_container_bytes=request.max_container_bytes,
            force=request.force,
            control=control,
        )
        return OperationResult(
            operation=operation,
            output_path=str(core_result.output_path),
            title="hide_success",
            details=_hide_details(input_path.name, core_result),
        )

    if operation == "extract":
        assert output_path is not None
        destination, decoded = extract_file(
            input_path,
            output_path,
            credential=credential,
            force=request.force,
            max_pixels=request.max_pixels,
            max_file_bytes=request.max_file_bytes,
            max_container_bytes=request.max_container_bytes,
            control=control,
        )
        return OperationResult(
            operation=operation,
            output_path=str(destination),
            title="extract_success",
            details=_decoded_details(decoded),
        )

    if operation == "encrypt":
        assert output_path is not None
        core_result = encrypt_file(
            input_path,
            output_path,
            credential=credential,
            force=request.force,
            max_file_bytes=request.max_file_bytes,
            control=control,
        )
        return OperationResult(
            operation=operation,
            output_path=str(core_result.output_path),
            title="encrypt_success",
            details=_encrypt_details(input_path.name, core_result),
        )

    if operation == "decrypt":
        assert output_path is not None
        destination, decoded = decrypt_encrypted_file(
            input_path,
            output_path,
            credential=credential,
            force=request.force,
            max_file_bytes=request.max_file_bytes,
            max_container_bytes=request.max_container_bytes,
            control=control,
        )
        return OperationResult(
            operation=operation,
            output_path=str(destination),
            title="decrypt_success",
            details=_decoded_details(decoded),
        )

    raise AssertionError("unreachable operation")


def _verify(request, input_path, credential, control):
    """Authenticate and hash one private encrypted copy; never write plaintext."""
    _validate_limits(request.max_file_bytes)

    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def changed():
        return _ValidationError("input_changed", "验证期间输入文件发生变化")

    # Keep the original handle for change checks, but only read its bytes during
    # capture. Metadata checks are advisory; the copy binds both result digests.
    with input_path.open("rb", buffering=0) as original:
        initial = os.fstat(original.fileno())
        _check_container_budget(initial.st_size, request.max_container_bytes)

        def check_original():
            control.check()
            try:
                unchanged = (identity(os.fstat(original.fileno())) == identity(initial)
                             and identity(input_path.stat()) == identity(initial))
            except OSError as exc:
                raise changed() from exc
            if not unchanged:
                raise changed()

        signature = original.read(8)
        original.seek(0)
        # Reject known resource excess before allocating temporary disk space.
        # Full PNG bytes can exceed its payload budget (e.g. ancillary chunks).
        if signature == b"\x89PNG\r\n\x1a\n":
            kind = "png"
            with Image.open(original) as image:
                _check_pixels(image.size, request.max_pixels)
        elif signature == MAGIC:
            kind = "saes"
            _checked_container_header(original, request.max_file_bytes)
        elif signature[:6] in (b"GIF87a", b"GIF89a"):
            # Bounded capture comes first. Parsing/authentication then use only
            # that captured copy, preserving the relationship between both hashes.
            kind = "gif"
        else:
            raise _ValidationError("unsupported_container", "不支持的加密容器")
        original.seek(0)
        check_original()
        resources = _recovery_resources(initial.st_size, request.operation)
        if resources.temporary_required > resources.temporary_free:
            raise _TemporarySpaceError()

        # Only encrypted container bytes are written here. The private directory
        # and closed writer keep subsequent decoding independent of the source.
        with TemporaryDirectory(prefix="moyle-verify-") as directory:
            captured = Path(directory) / "container"
            captured_digest = hashlib.sha256()
            completed = 0
            control.report("capture", 0, initial.st_size)
            check_original()
            with captured.open("xb") as destination:
                while True:
                    control.check()
                    remaining = initial.st_size - completed
                    chunk = original.read(min(1024 * 1024, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        raise changed()
                    destination.write(chunk)
                    captured_digest.update(chunk)
                    completed += len(chunk)
                    control.report("capture", completed, initial.st_size)
                    check_original()
            if completed != initial.st_size:
                raise changed()
            check_original()

            if kind in {"png", "gif"}:
                decoded = decode_image(captured, credential=credential, max_pixels=request.max_pixels,
                                       max_file_bytes=request.max_file_bytes,
                                       max_container_bytes=request.max_container_bytes, control=control)
            else:
                decoded = decode_encrypted_file(captured, credential=credential,
                                                max_file_bytes=request.max_file_bytes, control=control)
            digest = hashlib.sha256()
            completed = 0
            control.report("hash", 0, initial.st_size)
            check_original()
            with captured.open("rb", buffering=0) as stream:
                while True:
                    control.check()
                    remaining = initial.st_size - completed
                    chunk = stream.read(min(1024 * 1024, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        raise changed()
                    digest.update(chunk)
                    completed += len(chunk)
                    control.report("hash", completed, initial.st_size)
                    check_original()
            # Also reject accidental changes to the private copy itself.
            if completed != initial.st_size or digest.digest() != captured_digest.digest():
                raise changed()
        check_original()
    details = _decoded_details(decoded)
    details.update(container_format=kind, payload_sha256=decoded.sha256_hex,
                   input_sha256=digest.hexdigest(), input_size=str(completed), verified="yes")
    return OperationResult(operation=request.operation, title=request.operation + "_success", details=details)


def friendly_error(exc: Exception, language: str = "zh_CN") -> str:
    """Return a localized, actionable error without echoing exception data."""

    english = language == "en_US"
    if isinstance(exc, OperationCancelled):
        return "Operation cancelled safely." if english else "操作已安全取消。"
    code = getattr(exc, "code", "")
    if code:
        messages = _VALIDATION_MESSAGES.get(code, _VALIDATION_MESSAGES["invalid_input"])
        return messages[1 if english else 0]

    if isinstance(exc, AuthenticationError):
        return (
            "Authentication failed. Check the password or key file and ensure the data was not modified."
            if english
            else "认证失败。请检查口令或密钥文件，并确认文件未被修改。"
        )
    if isinstance(exc, FileNotFoundError):
        return "The selected file was not found." if english else "找不到所选文件，请重新选择。"
    if isinstance(exc, FileExistsError):
        return (
            "The output file already exists. Choose another path or explicitly allow overwrite."
            if english
            else "输出文件已存在。请选择其他路径，或明确允许覆盖。"
        )
    if isinstance(exc, PermissionError):
        return (
            "Permission was denied. Choose a writable location and check file access."
            if english
            else "没有文件访问权限。请选择可写位置并检查文件权限。"
        )
    if isinstance(exc, (IsADirectoryError, NotADirectoryError)):
        return "Select a valid file path." if english else "请选择有效的文件路径。"
    if isinstance(exc, UnidentifiedImageError):
        return (
            "The selected file is not a recognizable image."
            if english
            else "所选文件不是可识别的图片。"
        )

    raw = str(exc)
    if isinstance(exc, ValueError):
        if "输出文件必须使用" in raw:
            return ("Match the output extension to the carrier: .gif for GIF, .png for other images."
                    if english else "请让输出后缀与载体匹配：GIF 使用 .gif，其他图片使用 .png。")
        if "不一致" in raw or "do not match" in raw.lower():
            return (
                "The passwords do not match. Enter the same password twice."
                if english
                else "两次输入的口令不一致，请重新输入。"
            )
        if "不能为空" in raw or "empty" in raw.lower():
            return "The password cannot be empty." if english else "口令不能为空。"
        if "密钥" in raw or "key" in raw.lower():
            return (
                "The key file is invalid or damaged. Select a valid .stegkey file."
                if english
                else "密钥文件无效或已损坏，请选择有效的 .stegkey 文件。"
            )
        return (
            "The request is invalid. Check the selected files and settings."
            if english
            else "请求参数无效，请检查所选文件和设置。"
        )
    if isinstance(exc, StegError):
        if "GIF" in raw and ("已含" in raw or "多个" in raw or "版本" in raw):
            return ("This GIF contains an existing, duplicate or unsupported MoyleSteg extension. Choose the original carrier or check the producing app version."
                    if english else "GIF 含已有、重复或不支持版本的 MoyleSteg 扩展。隐藏时请选择原始载体，恢复时请核对生成端版本。")
        if "资源上限" in raw or "安全解码上限" in raw or "像素数超过" in raw:
            return (
                "The file exceeds the processing resource limit. Use a smaller file or image."
                if english else "文件超过处理资源上限，请使用更小的文件或图片。"
            )
        if "容量不足" in raw or "像素数超过" in raw or "自动放大" in raw:
            return (
                "The cover image does not have enough safe capacity. Choose a larger image or enable auto-resize."
                if english
                else "载体图片容量不足。请选择更大的图片或启用自动扩容。"
            )
        if "未找到" in raw or "格式" in raw or "头部" in raw:
            return (
                "No supported encrypted payload was found, or the file is damaged."
                if english
                else "未找到受支持的加密数据，或文件已经损坏。"
            )
        return (
            "The operation could not be completed because the file is invalid or damaged."
            if english
            else "操作无法完成，文件可能无效或已损坏。"
        )
    if isinstance(exc, OSError):
        return (
            "A file operation failed. Check the path, free space, and permissions."
            if english
            else "文件操作失败。请检查路径、可用空间和权限。"
        )
    return (
        "The operation failed. Check the selected files and settings."
        if english
        else "操作失败，请检查所选文件和设置。"
    )


_VALIDATION_MESSAGES: dict[str, tuple[str, str]] = {
    "recovery_resource_limit": (
        "文件超过当前恢复预算。请勿缩放、裁剪或重新保存原隐写 PNG／GIF；确认设备资源充足后，可提高恢复预算。",
        "The file exceeds the current recovery budget. Do not resize, crop, or re-save the original steganographic PNG/GIF. Increase the recovery budget only after confirming sufficient device resources.",
    ),
    "source_resource_limit": (
        "文件或载体超过当前处理预算。请选择更小的秘密文件或合适尺寸的载体；确认设备资源充足后也可调整预算。",
        "The secret file or cover exceeds the current processing budget. Choose a smaller secret file or a suitably sized cover, or adjust the budget after confirming sufficient device resources.",
    ),
    "container_resource_limit": (
        "完整容器超过当前容器字节预算。请保留原文件，勿缩放、裁剪或重新保存原隐写 PNG／GIF；确认设备和临时磁盘资源充足后，可提高容器预算。",
        "The complete container exceeds the container byte budget. Preserve the original file; do not resize, crop, or re-save the steganographic PNG/GIF. Increase the container budget only after checking device and temporary disk resources.",
    ),
    "container_budget_invalid": ("容器预算必须为大于零的整数字节数。", "The container budget must be a positive integer number of bytes."),
    "temporary_space": (
        "临时磁盘可用空间不足，无法安全验证完整容器。请释放系统临时目录所在磁盘的空间后重试；保留原隐写文件，不要缩放或重新保存。",
        "The temporary disk has insufficient free space to verify the complete container safely. Free space on the system temporary volume and try again. Preserve the original steganographic file without resizing or re-saving it.",
    ),
    "unsupported_container": ("请选择本工具生成的 PNG、GIF 或 SAES 加密文件。", "Select a PNG, GIF or SAES encrypted container created by this tool."),
    "input_changed": ("读取期间输入文件发生变化，请等待文件保存或同步完成后重试。", "The input changed while being read. Wait for saving or syncing to finish, then try again."),
    "unknown_operation": ("不支持此操作。", "This operation is not supported."),
    "output_required": ("必须明确选择输出路径。", "Choose an explicit output path."),
    "output_absolute": ("输出路径必须是绝对路径。", "The output path must be absolute."),
    "output_directory_operation": (
        "仅提取或解密支持按原文件名恢复到目录。",
        "Restoring an original filename to a directory is supported only for extraction or decryption.",
    ),
    "output_destination_conflict": (
        "请仅选择恢复目录或指定输出文件，不能同时设置。",
        "Choose either a restore directory or an explicit output file, not both.",
    ),
    "output_directory_absolute": (
        "恢复目录必须是绝对路径。",
        "The restore directory must be an absolute path.",
    ),
    "output_directory_invalid": (
        "所选恢复目录不是文件夹，请选择有效目录。",
        "The selected restore destination is not a directory. Choose a valid folder.",
    ),
    "restore_filename_unsafe": (
        "原文件名不适合安全恢复到 Windows。请改为指定输出文件名。",
        "The original filename is unsafe for restoration on Windows. Choose an explicit output filename.",
    ),
    "restore_destination_escape": (
        "原文件名解析后的保存位置不在所选目录内，请选择其他目录或指定输出文件名。",
        "The resolved destination is outside the selected directory. Choose another folder or an explicit output filename.",
    ),
    "restore_target_directory": (
        "原文件名对应的位置已是文件夹，请选择其他目录或指定输出文件名。",
        "A folder already uses the original filename. Choose another directory or an explicit output filename.",
    ),
    "output_collision": (
        "输出路径不能与输入文件、载体图片或密钥文件相同。",
        "The output path must differ from every input, cover image, and key file.",
    ),
    "input_required": ("必须选择输入文件。", "Choose an input file."),
    "cover_required": ("必须选择载体图片。", "Choose a cover image."),
    "image_required": ("必须选择图片。", "Choose an image."),
    "credential_mode": ("请选择有效的凭据模式。", "Choose a valid credential mode."),
    "password_empty": ("口令不能为空。", "The password cannot be empty."),
    "password_mismatch": (
        "两次输入的口令不一致，请重新输入。",
        "The passwords do not match. Enter the same password twice.",
    ),
    "key_required": ("必须选择密钥文件。", "Choose a key file."),
    "invalid_input": ("请求参数无效。", "The request is invalid."),
}


def _same_path(left: Path, right: Path) -> bool:
    return _core_same_path(left, right)


def _validate_output(request: OperationRequest) -> Path:
    if not request.output_path:
        raise _ValidationError("output_required", "必须明确选择输出路径")
    output = Path(request.output_path)
    if not output.is_absolute():
        raise _ValidationError("output_absolute", "输出路径必须为绝对路径")

    protected = [request.input_path, request.cover_path, request.key_path]
    if any(value and _same_path(output, Path(value)) for value in protected):
        raise _ValidationError(
            "output_collision", "输出路径不能与输入、载体或密钥文件相同"
        )
    if output.exists() and not request.force:
        raise FileExistsError("输出文件已存在")
    validate_operation_paths(inputs=tuple(Path(value) for value in (request.input_path, request.cover_path) if value),
                             output=output, key_path=Path(request.key_path) if request.key_path else None,
                             force=request.force)
    return output


def _validate_output_directory(request: OperationRequest) -> Path:
    if request.operation not in {"extract", "decrypt"}:
        raise _ValidationError("output_directory_operation", "此操作不支持恢复目录")
    if request.output_path:
        raise _ValidationError("output_destination_conflict", "不能同时指定输出文件和目录")
    directory = Path(request.output_directory)
    if not directory.is_absolute():
        raise _ValidationError("output_directory_absolute", "恢复目录必须是绝对路径")
    if directory.exists() and not directory.is_dir():
        raise _ValidationError("output_directory_invalid", "恢复目录不是文件夹")
    return directory.resolve(strict=False)


def _original_destination(request: OperationRequest, directory: Path, filename: str) -> Path:
    # Encrypted metadata is authenticated, but its filename still has to be safe
    # on the destination filesystem. Apply Windows rules on every platform.
    try:
        filename = _safe_filename(filename)
    except (StegError, ValueError, TypeError) as error:
        raise _ValidationError("restore_filename_unsafe", "原文件名不安全") from error
    destination = directory / filename
    if destination.resolve(strict=False).parent != directory:
        raise _ValidationError("restore_destination_escape", "恢复路径离开了所选目录")
    destination = _validate_output(
        replace(request, output_path=str(destination), output_directory="")
    )
    if destination.is_dir():
        raise _ValidationError("restore_target_directory", "原文件名对应的位置是文件夹")
    return destination


def _required_input(value: str, kind: str) -> Path:
    code = f"{kind}_required"
    messages = {
        "input": "必须选择输入文件",
        "cover": "必须选择载体图片",
        "image": "必须选择图片",
    }
    if not value:
        raise _ValidationError(code, messages[kind])
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError("所选文件不存在")
    return path


def _credential(request: OperationRequest, *, for_write: bool) -> Credential:
    if request.credential_mode == "password":
        if not request.password:
            raise _ValidationError("password_empty", "口令不能为空")
        if for_write and request.password != request.password_confirm:
            raise _ValidationError("password_mismatch", "两次输入的口令不一致")
        return Credential.from_password(request.password)
    if request.credential_mode == "key_file":
        if not request.key_path:
            raise _ValidationError("key_required", "必须选择密钥文件")
        key_path = _required_input(request.key_path, "input")
        return Credential.from_key_file(key_path)
    raise _ValidationError("credential_mode", "凭据模式必须为 password 或 key_file")


def _mode_name(mode: int) -> str:
    if mode == MODE_PASSWORD:
        return "password"
    if mode == MODE_KEY_FILE:
        return "key_file"
    raise ValueError("未知凭据模式")


def _bool_name(value: bool) -> str:
    return "yes" if value else "no"


def _decoded_details(decoded: DecodedPayload) -> dict[str, str]:
    return {
        "filename": decoded.filename,
        "original_size": str(decoded.original_size),
        "stored_size": str(decoded.stored_size),
        "sha256": decoded.sha256_hex,
        "payload_sha256": decoded.sha256_hex,
        "compressed": _bool_name(decoded.compressed),
        "credential_mode": _mode_name(decoded.credential_mode),
        "algorithm": "AES-256-GCM",
    }


def _hide_details(filename: str, result: HideResult) -> dict[str, str]:
    return {
        "filename": filename,
        "original_size": str(result.original_size),
        "stored_size": str(result.stored_size),
        "sha256": result.sha256_hex,
        "payload_sha256": result.sha256_hex,
        "compressed": _bool_name(result.compressed),
        "width": str(result.image_width),
        "height": str(result.image_height),
        "capacity": str(result.capacity_bytes),
        "fill_ratio": f"{result.fill_ratio:.6f}",
        "credential_mode": _mode_name(result.credential_mode),
        "algorithm": result.algorithm,
        "container_format": result.container_format,
        "frame_count": str(result.frame_count),
        "output_bytes": str(result.output_bytes),
    }


def _encrypt_details(filename: str, result: EncryptResult) -> dict[str, str]:
    return {
        "filename": filename,
        "original_size": str(result.original_size),
        "stored_size": str(result.stored_size),
        "sha256": result.sha256_hex,
        "payload_sha256": result.sha256_hex,
        "compressed": _bool_name(result.compressed),
        "credential_mode": _mode_name(result.credential_mode),
        "algorithm": result.algorithm,
    }
