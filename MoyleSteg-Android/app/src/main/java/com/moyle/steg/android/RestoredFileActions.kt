package com.moyle.steg.android

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.webkit.MimeTypeMap
import java.io.File
import java.nio.ByteBuffer
import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction
import java.util.Locale

sealed interface OpenOutcome {
    /** The chooser started; the user may still cancel or see Android's no-app message. */
    data object ChooserStarted : OpenOutcome
    data class Unavailable(val message: String) : OpenOutcome
}

/** Type hints and explicit user-requested viewing for an authenticated, already saved result. */
object RestoredFileActions {
    private const val UNKNOWN = "application/octet-stream"
    private const val HEADER_BYTES = 4096

    /**
     * Pass the authenticated original filename, not the carrier or private staging filename.
     * Reads at most 4 KiB for any file size. MIME inference is a hint, not format validation.
     */
    fun mimeFor(staged: File, filename: String): String {
        val extension = filename.substringAfterLast('/').substringAfterLast('\\')
            .substringAfterLast('.', "").lowercase(Locale.ROOT)
        val namedType = extensionTypes[extension]
            ?: MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension)
        val header = ByteArray(HEADER_BYTES)
        try {
            var count = 0
            staged.inputStream().use { input ->
                while (count < header.size) {
                    val read = input.read(header, count, header.size - count)
                    if (read <= 0) break
                    count += read
                }
            }
            fun starts(vararg bytes: Int) = count >= bytes.size && bytes.indices.all {
                (header[it].toInt() and 255) == bytes[it]
            }
            fun ascii(value: String, offset: Int = 0) = count >= offset + value.length &&
                value.indices.all { header[offset + it].toInt() == value[it].code }

            // A package stays a package; the opening API never adds install actions or privileges.
            if (extension == "apk") return "application/vnd.android.package-archive"
            when {
                starts(137, 80, 78, 71, 13, 10, 26, 10) -> return "image/png"
                starts(255, 216, 255) -> return "image/jpeg"
                ascii("GIF87a") || ascii("GIF89a") -> return "image/gif"
                ascii("%PDF-") -> return "application/pdf"
                ascii("RIFF") && ascii("WEBP", 8) -> return "image/webp"
                ascii("RIFF") && ascii("WAVE", 8) -> return "audio/wav"
                starts(80, 75, 3, 4) || starts(80, 75, 5, 6) || starts(80, 75, 7, 8) -> {
                    // DOCX/XLSX/PPTX and other ZIP containers need their specific viewer subtype.
                    return if (extension in zipContainerExtensions && namedType != null) namedType
                    else "application/zip"
                }
            }
            if (ascii("ftyp", 4) && count >= 12) {
                when (String(header, 8, 4, Charsets.US_ASCII)) {
                    "avif", "avis" -> return "image/avif"
                    "heic", "heix", "hevc", "hevx" -> return "image/heic"
                    "mif1", "msf1" -> return "image/heif"
                    "M4A ", "M4B " -> return "audio/mp4"
                    "qt  " -> return "video/quicktime"
                    "isom", "iso2", "iso3", "iso4", "iso5", "iso6", "mp41", "mp42", "avc1", "M4V ", "dash" ->
                        return if (extension == "m4a" || extension == "m4b") "audio/mp4" else "video/mp4"
                }
            }
            if (namedType != null && namedType != UNKNOWN) return namedType

            val text = textPrefix(header, count, staged.length() <= count.toLong()) ?: return UNKNOWN
            val leading = text.trimStart('\uFEFF', ' ', '\t', '\r', '\n').lowercase(Locale.ROOT)
            return when {
                leading.startsWith("<!doctype html") || leading.startsWith("<html") ||
                    leading.startsWith("<head") || leading.startsWith("<body") -> "text/html"
                leading.startsWith("<svg") -> "image/svg+xml"
                leading.startsWith("<?xml") -> "application/xml"
                else -> "text/plain"
            }
        } finally { header.fill(0) }
    }

    /** Only one content URI and a temporary read grant cross the app boundary. */
    fun viewIntent(uri: Uri, mime: String): Intent {
        require(uri.scheme == "content" && !uri.authority.isNullOrBlank()) {
            "打开恢复文件需要有效的 content URI。"
        }
        val viewType = if (mime == UNKNOWN || mime.isBlank()) "*/*" else mime
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, viewType)
            clipData = ClipData.newRawUri("恢复的文件", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    /** Call only after the user taps Open, never as a restore/save side effect. */
    fun open(context: Context, uri: Uri, mime: String): OpenOutcome {
        val chooser = Intent.createChooser(viewIntent(uri, mime), "选择打开方式").apply {
            // createChooser copies the target's ClipData and read grant to the chooser.
            if (context !is Activity) addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return try {
            // Android 11+ supports this without package visibility queries or a manifest queries entry.
            context.startActivity(chooser)
            OpenOutcome.ChooserStarted
        } catch (_: ActivityNotFoundException) {
            OpenOutcome.Unavailable("没有找到可打开此类文件的应用。文件仍在保存位置，可通过文件管理器选择其他应用打开。")
        } catch (_: SecurityException) {
            OpenOutcome.Unavailable("系统暂未允许应用读取此文件。文件仍在保存位置，请从文件管理器打开，或另存后重试。")
        }
    }

    private fun textPrefix(header: ByteArray, count: Int, complete: Boolean): String? {
        if (count == 0) return null
        val charset = when {
            count >= 2 && header[0] == (-1).toByte() && header[1] == (-2).toByte() -> Charsets.UTF_16LE
            count >= 2 && header[0] == (-2).toByte() && header[1] == (-1).toByte() -> Charsets.UTF_16BE
            else -> Charsets.UTF_8
        }
        val decoded = CharBuffer.allocate(count)
        val result = charset.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(header, 0, count), decoded, complete)
        if (result.isError) return null
        decoded.flip()
        val text = decoded.toString()
        if (text.isEmpty() || text.any { it.isISOControl() && it !in "\t\n\r\u000C" }) return null
        return text
    }

    private val extensionTypes = mapOf(
        "txt" to "text/plain", "log" to "text/plain", "md" to "text/markdown",
        "csv" to "text/csv", "json" to "application/json", "xml" to "application/xml",
        "html" to "text/html", "htm" to "text/html", "svg" to "image/svg+xml",
        "png" to "image/png", "jpg" to "image/jpeg", "jpeg" to "image/jpeg", "gif" to "image/gif",
        "pdf" to "application/pdf", "zip" to "application/zip",
        "mp4" to "video/mp4", "m4v" to "video/mp4", "m4a" to "audio/mp4", "m4b" to "audio/mp4",
        "mp3" to "audio/mpeg", "wav" to "audio/wav", "ogg" to "audio/ogg",
        "doc" to "application/msword", "xls" to "application/vnd.ms-excel", "ppt" to "application/vnd.ms-powerpoint",
        "docx" to "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx" to "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx" to "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "epub" to "application/epub+zip", "apk" to "application/vnd.android.package-archive"
    )

    private val zipContainerExtensions = setOf(
        "docx", "docm", "dotx", "dotm", "xlsx", "xlsm", "xltx", "xltm", "xlsb",
        "pptx", "pptm", "potx", "potm", "ppsx", "ppsm", "sldx", "sldm",
        "odt", "ods", "odp", "odg", "epub", "apk", "jar"
    )
}
