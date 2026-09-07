package com.moyle.steg.android

import android.Manifest
import android.app.Application
import android.content.ContentValues
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.provider.OpenableColumns
import androidx.annotation.RequiresApi
import androidx.core.content.FileProvider
import com.moyle.steg.core.Control
import com.moyle.steg.core.StegException
import com.moyle.steg.core.safeFilename
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.nio.channels.Channels
import java.nio.channels.FileChannel
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.BasicFileAttributes
import java.security.MessageDigest

data class SavedDownload(val uri: Uri, val displayName: String, val mime: String, val displayPath: String)

fun interface DownloadWriter {
    fun save(staged: File, suggestedName: String, mime: String, expectedSha256: String, control: Control): SavedDownload
}

class DownloadPermissionException(cause: Throwable? = null) :
    StegException("需要存储权限才能保存到 Download；已恢复的文件仍可重试保存。", cause)

/** Publishes an authenticated private result. The caller retains ownership of the staged file. */
class DownloadsExporter(private val app: Application) : DownloadWriter {
    private val resolver get() = app.contentResolver

    fun requiresLegacyPermission(): Boolean = Build.VERSION.SDK_INT <= 28 &&
        app.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED

    override fun save(staged: File, suggestedName: String, mime: String, expectedSha256: String, control: Control): SavedDownload {
        control.check()
        val name = safeFilename(suggestedName)
        if (name.toByteArray(Charsets.UTF_8).size > 180)
            throw StegException("保存文件名过长，请使用较短的文件名。")
        if (requiresLegacyPermission()) throw DownloadPermissionException()
        if (!staged.isFile) throw StegException("待保存的私有文件已不存在，请重新恢复。")
        val preferredMime = mime.ifBlank { "application/octet-stream" }
        try {
            // Authentication happened upstream; recheck the exact private bytes before any public creation.
            DocumentStore(app).validateStaged(staged, expectedSha256, control)
            val length = staged.length()
            return if (Build.VERSION.SDK_INT >= 29)
                saveMediaStore(staged, name, preferredMime, expectedSha256, length, control)
            else saveLegacy(staged, name, preferredMime, expectedSha256, length, control)
        } catch (error: SecurityException) {
            if (Build.VERSION.SDK_INT <= 28) throw DownloadPermissionException(error)
            throw StegException("系统拒绝了 Download 保存请求；已恢复的文件仍可重试保存。", error)
        } catch (error: IOException) {
            throw StegException("保存到 Download 失败，请检查剩余空间后重试。", error)
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun saveMediaStore(staged: File, name: String, mime: String, expectedHash: String,
                              length: Long, control: Control): SavedDownload {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        control.check()
        // Always insert. Never query an existing filename and then reopen it for writing.
        val uri = resolver.insert(MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
            ?: throw StegException("系统未能在 Download 中创建文件，请重试。")
        try {
            control.check()
            val descriptor = resolver.openFileDescriptor(uri, "w")
                ?: throw StegException("无法打开新建的 Download 文件。")
            ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { output ->
                staged.inputStream().use { verifyStream(it, expectedHash, length, control, "保存到 Download", output) }
                output.flush()
                output.fd.sync()
            }
            (resolver.openInputStream(uri) ?: throw StegException("无法回读 Download 文件，已拒绝发布。"))
                .use { verifyStream(it, expectedHash, length, control, "回读验证 Download") }
            // The system may number or shorten a duplicate name. Return its actual metadata.
            val result = describeSaved(uri, mime)
            control.check()
            if (resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null) != 1)
                throw StegException("系统未能发布已验证的 Download 文件，请重试。")
            // This is the commit point. Cancellation after publication must not revoke a successful save.
            return result
        } catch (error: Throwable) {
            val removed = runCatching { resolver.delete(uri, null, null) == 1 }.getOrDefault(false)
            if (!removed) throw StegException("保存未完成，且系统无法清理本次 Download 输出；请检查 Download 目录后重试。", error)
            throw error
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun describeSaved(uri: Uri, preferredMime: String): SavedDownload {
        val columns = arrayOf(OpenableColumns.DISPLAY_NAME, MediaStore.MediaColumns.RELATIVE_PATH, MediaStore.MediaColumns.MIME_TYPE)
        return resolver.query(uri, columns, null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) throw StegException("无法确认 Download 中的实际文件名。")
            fun value(column: String): String? {
                val index = cursor.getColumnIndex(column)
                return if (index < 0 || cursor.isNull(index)) null else cursor.getString(index)
            }
            val name = value(OpenableColumns.DISPLAY_NAME)?.takeIf { it.isNotBlank() }
                ?: throw StegException("无法确认 Download 中的实际文件名。")
            val relative = value(MediaStore.MediaColumns.RELATIVE_PATH)?.takeIf { it.isNotBlank() }
                ?: Environment.DIRECTORY_DOWNLOADS
            SavedDownload(uri, name, value(MediaStore.MediaColumns.MIME_TYPE)?.takeIf { it.isNotBlank() } ?: preferredMime,
                "${relative.trimEnd('/')}/$name")
        } ?: throw StegException("无法确认 Download 中的实际文件名。")
    }

    private data class NewLegacyFile(val file: File, val channel: FileChannel, val key: Any?)

    /** API 26-28 cannot hide a pending shared file; no success is returned before the full readback. */
    private fun saveLegacy(staged: File, name: String, mime: String, expectedHash: String,
                           length: Long, control: Control): SavedDownload {
        val directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        if (!directory.isDirectory && !directory.mkdirs()) throw StegException("无法创建公共 Download 目录。")
        val target = createLegacy(directory, name, control)
        try {
            // CREATE_NEW opens the newly-created inode itself: no create-then-reopen truncation race.
            target.channel.use { channel ->
                val output = Channels.newOutputStream(channel)
                staged.inputStream().use { verifyStream(it, expectedHash, length, control, "保存到 Download", output) }
                output.flush()
                channel.force(true)
            }
            if (!sameLegacyFile(target)) throw StegException("Download 文件在保存期间被替换，已停止保存。")
            target.file.inputStream().use { verifyStream(it, expectedHash, length, control, "回读验证 Download") }
            if (!sameLegacyFile(target)) throw StegException("Download 文件在校验期间被替换，已停止保存。")
            val uri = FileProvider.getUriForFile(app, "${app.packageName}.downloads", target.file)
            val result = SavedDownload(uri, target.file.name, mime, "${Environment.DIRECTORY_DOWNLOADS}/${target.file.name}")
            control.check()
            // Logical commit on old Android. Nothing that checks cancellation follows it.
            return result
        } catch (error: Throwable) {
            runCatching { target.channel.close() }
            val removed = runCatching {
                if (!Files.exists(target.file.toPath(), LinkOption.NOFOLLOW_LINKS)) true
                else if (sameLegacyFile(target)) Files.deleteIfExists(target.file.toPath())
                else false // Never delete another writer's replacement.
            }.getOrDefault(false)
            if (!removed) throw StegException("保存未完成；Download 文件已被替换或无法清理，请检查本次输出后重试。", error)
            throw error
        }
    }

    private fun createLegacy(directory: File, name: String, control: Control): NewLegacyFile {
        val dot = name.lastIndexOf('.').takeIf { it > 0 } ?: name.length
        val stem = name.substring(0, dot)
        val extension = name.substring(dot)
        for (number in 0..9999) {
            control.check()
            val file = File(directory, if (number == 0) name else "$stem ($number)$extension")
            val channel = try {
                FileChannel.open(file.toPath(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)
            } catch (_: FileAlreadyExistsException) { continue }
            // Some filesystems don't expose file keys. On those, only exclusive creation is guaranteed.
            val key = runCatching { legacyFileKey(file) }.getOrNull()
            return NewLegacyFile(file, channel, key)
        }
        throw StegException("Download 中同名文件过多，请使用其他文件名。")
    }

    private fun legacyFileKey(file: File): Any? =
        Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS).fileKey()

    private fun sameLegacyFile(target: NewLegacyFile): Boolean =
        target.key == null || legacyFileKey(target.file) == target.key

    /** Fixed-size working memory; all file lengths and counts stay Long through the full 1 GiB path. */
    private fun verifyStream(input: InputStream, expectedHash: String, length: Long, control: Control,
                             stage: String, output: OutputStream? = null) {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(65536)
        var count = 0L
        val scale = maxOf(1L, length / Int.MAX_VALUE + if (length % Int.MAX_VALUE == 0L) 0L else 1L)
        try {
            while (true) {
                control.check()
                val remaining = length - count
                val requested = if (remaining >= buffer.size) buffer.size else (remaining + 1L).toInt()
                val read = input.read(buffer, 0, requested)
                if (read < 0) break
                if (read == 0) throw StegException("文件读取无法继续，已停止保存。")
                if (read.toLong() > remaining) throw StegException("输出长度与已验证文件不一致，已拒绝发布。")
                output?.write(buffer, 0, read)
                digest.update(buffer, 0, read)
                count += read.toLong()
                control.report(stage, (count / scale).toInt(), (length / scale).toInt())
            }
            control.check()
            val observed = digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
            if (count != length || observed != expectedHash)
                throw StegException("Download 输出与已验证文件的 SHA-256 或长度不一致，已拒绝发布。")
        } finally { buffer.fill(0) }
    }
}
