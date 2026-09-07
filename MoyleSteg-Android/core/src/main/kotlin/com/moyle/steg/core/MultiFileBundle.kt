package com.moyle.steg.core

import java.io.File
import java.io.BufferedOutputStream
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import java.io.RandomAccessFile
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.BasicFileAttributes
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.Inflater
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class BundleSource(val file: File, val name: String)
data class BundleEntry(val index: Int, val name: String, val size: Long, val sha256: String)
data class BundleInfo(val entries: List<BundleEntry>, val totalBytes: Long, val archiveBytes: Long)
data class BundlePackage(val file: File, val info: BundleInfo)

/** Shared, injectable observation of private filesystem capacity; it does not reserve storage. */
class BundleDiskPolicy(private val availableBytes: (File) -> Long = { it.usableSpace }) {
    companion object {
        const val RESERVE_BYTES = 32L * 1024 * 1024
        internal const val SPACE_MESSAGE = "私有临时磁盘空间不足；请释放空间后重试。处理时需要保留 32 MiB 余量。"
    }

    /** Existing files have already reduced available space; count only remaining new writes. */
    fun requireAdditional(directory: File, bytesPending: Long) {
        demand(bytesPending >= 0, "私有工作空间预算无效。")
        val available = try { availableBytes(directory) } catch (error: IOException) { throw mapFailure(error) }
        // Subtract in this order so an untrusted or extremely large size cannot overflow.
        if (available < RESERVE_BYTES || bytesPending > available - RESERVE_BYTES)
            throw PrivateDiskSpaceException()
    }

    /** Android's ErrnoException is inspected through its cause text without an Android dependency. */
    fun mapFailure(error: IOException): StegException {
        var next: Throwable? = error
        repeat(8) {
            // FileSystemException.message embeds file paths. Only its structured
            // reason describes the OS failure; a filename is not an errno.
            val detail = if (next is java.nio.file.FileSystemException) (next as java.nio.file.FileSystemException).reason
                else next?.message
            val message = detail.orEmpty().lowercase(java.util.Locale.ROOT)
            if (listOf("enospc", "edquot", "no space left", "not enough space", "disk full",
                    "quota exceeded", "磁盘空间不足", "磁盘已满", "存储空间不足").any(message::contains))
                return PrivateDiskSpaceException(error)
            next = next?.cause
        }
        return StegException("多文件包读写失败，请检查文件与可用空间。", error)
    }
}

class PrivateDiskSpaceException(cause: Throwable? = null) : StegException(BundleDiskPolicy.SPACE_MESSAGE, cause)

object MultiFileBundle {
    const val FILENAME = "MoyleSteg-files.zip"
    const val MARKER = "MOYLESTEG-BUNDLE-V1"
    private val markerBytes = MARKER.toByteArray(Charsets.US_ASCII)
    private const val CHUNK = 65536
    private const val MAX_ZIP32 = 0xfffffffeL
    private const val CENTRAL_LIMIT = 128 * 1024
    private const val PROFILE_ERROR = "多文件包格式无效或使用了不支持的 ZIP 功能。"
    private const val CHANGED_ERROR = "读取期间文件发生变化，请等待保存、同步或下载完成后重试。"

    private data class Record(val index: Int, val name: String, val path: ByteArray,
                              val version: Int, val flags: Int, val method: Int,
                              val time: Int, val date: Int, val crc: Long,
                              val compressed: Long, val size: Long, val localOffset: Long,
                              var dataOffset: Long = 0)
    private data class Directory(val records: List<Record>, val bytes: Long, val expanded: Long)
    private data class Snapshot(val file: File, val size: Long, val modified: Long, val key: Any?)

    /** Creates only a new private file. No source paths are used as destinations. */
    @JvmOverloads
    fun create(sources: List<BundleSource>, directory: File, maxTotalBytes: Long,
               maxArchiveBytes: Long, control: Control = Control(),
               diskPolicy: BundleDiskPolicy = BundleDiskPolicy()): BundlePackage = translated(diskPolicy) {
        budgets(maxTotalBytes, maxArchiveBytes)
        control.check()
        demand(sources.size in 1..100, "多文件任务需要 1 至 100 个文件。")
        var total = 0L
        val snapshots = sources.map { source ->
            checkedName(source.name)
            snapshot(source.file).also {
                demand(it.size <= MAX_ZIP32, "多文件包不支持 ZIP64 大小的单个文件。")
                total = addSize(total, it.size, maxTotalBytes)
            }
        }
        // Even an empty entry needs both headers and the encoded member name.
        val minimum = 22L + markerBytes.size + sources.sumOf { 76L + 2L * (5 + utf8(it.name).size) }
        demand(minimum <= maxArchiveBytes, "多文件包超过容器字节预算。")
        demand(directory.isDirectory || directory.mkdirs(), "无法创建私有临时目录。")
        val planned = plannedArchiveBytes(total, sources.size, maxArchiveBytes)
        diskPolicy.requireAdditional(directory, planned)
        control.check()
        val file = File.createTempFile("bundle-", ".zip", directory)
        var keep = false
        try {
            val entries = ArrayList<BundleEntry>(sources.size)
            FileOutputStream(file).use { output ->
                val bounded = LimitedOutput(output, minOf(maxArchiveBytes, MAX_ZIP32),
                    directory, diskPolicy, planned)
                // A close on the ZIP must not close the descriptor before sync.
                val borrowed = object : OutputStream() {
                    override fun write(b: Int) = bounded.write(b)
                    override fun write(b: ByteArray, offset: Int, length: Int) = bounded.write(b, offset, length)
                    override fun flush() = bounded.flush()
                    override fun close() = flush()
                }
                // Deflater emits small fragments and ZIP metadata may be written byte by
                // byte. Observe capacity for each bounded physical write, not every fragment.
                ZipOutputStream(BufferedOutputStream(borrowed, CHUNK), Charsets.UTF_8).use { zip ->
                    zip.setComment(MARKER)
                    zip.setLevel(6)
                    for ((at, source) in sources.withIndex()) {
                        control.check()
                        unchanged(snapshots[at])
                        val member = ZipEntry("%04d/%s".format(java.util.Locale.ROOT, at + 1, source.name)).apply {
                            // 2000-01-01 avoids ZIP extended timestamps across time zones.
                            time = 946684800000L
                            method = ZipEntry.DEFLATED
                        }
                        zip.putNextEntry(member)
                        val digest = sourceHash(source.file, snapshots[at].size, control, "打包文件", zip)
                        zip.closeEntry()
                        unchanged(snapshots[at])
                        entries += BundleEntry(at + 1, source.name, snapshots[at].size, digest)
                    }
                    zip.finish()
                    zip.flush()
                    output.fd.sync()
                    diskPolicy.requireAdditional(directory, 0)
                }
            }
            // Compare source content, not merely timestamps or file sizes.
            for (at in sources.indices) {
                control.check()
                unchanged(snapshots[at])
                val digest = sourceHash(sources[at].file, snapshots[at].size, control, "复核打包源文件")
                demand(digest == entries[at].sha256, CHANGED_ERROR)
                unchanged(snapshots[at])
            }
            control.report("回读多文件包")
            val verified = inspect(file, maxTotalBytes, maxArchiveBytes, control)
            demand(verified != null && verified.entries == entries && verified.totalBytes == total,
                "保存后的多文件包与源文件不一致。")
            diskPolicy.requireAdditional(directory, 0)
            control.check()
            keep = true
            BundlePackage(file, verified!!)
        } finally { if (!keep) file.delete() }
    }

    /** Ordinary archives are left intact; only the exact end comment opts in. */
    fun inspect(file: File, maxTotalBytes: Long, maxArchiveBytes: Long,
                control: Control = Control()): BundleInfo? = translated {
        budgets(maxTotalBytes, maxArchiveBytes)
        control.check()
        RandomAccessFile(file, "r").use { input ->
            val directory = readDirectory(input, maxTotalBytes, maxArchiveBytes, control) ?: return@use null
            val entries = directory.records.map { record ->
                BundleEntry(record.index, record.name, record.size, readEntry(input, record, control, "检查多文件包"))
            }
            demand(input.length() == directory.bytes, CHANGED_ERROR)
            control.check()
            BundleInfo(entries, directory.expanded, directory.bytes)
        }
    }

    /** Never uses an archive member path on disk. Only the selected, verified member is staged. */
    @JvmOverloads
    fun extract(file: File, entry: BundleEntry, directory: File, maxTotalBytes: Long,
                maxArchiveBytes: Long, control: Control = Control(),
                diskPolicy: BundleDiskPolicy = BundleDiskPolicy()): File = translated(diskPolicy) {
        budgets(maxTotalBytes, maxArchiveBytes)
        control.check()
        checkedName(entry.name)
        demand(Regex("[0-9a-f]{64}").matches(entry.sha256), "所选文件的验证信息无效。")
        RandomAccessFile(file, "r").use { input ->
            val parsed = readDirectory(input, maxTotalBytes, maxArchiveBytes, control)
                ?: throw StegException("不是 MoyleSteg 多文件包。")
            val record = parsed.records.getOrNull(entry.index - 1)
            demand(record != null && record.name == entry.name && record.size == entry.size,
                "所选文件与已验证的多文件包不一致。")
            demand(directory.isDirectory || directory.mkdirs(), "无法创建私有临时目录。")
            diskPolicy.requireAdditional(directory, entry.size)
            control.check()
            val output = File.createTempFile("member-", ".tmp", directory)
            var keep = false
            try {
                val hash = FileOutputStream(output).use { stream ->
                    val bounded = LimitedOutput(stream, entry.size, directory, diskPolicy, entry.size)
                    readEntry(input, record!!, control, "提取文件", bounded).also {
                        stream.flush(); stream.fd.sync(); diskPolicy.requireAdditional(directory, 0)
                    }
                }
                demand(hash == entry.sha256 && input.length() == parsed.bytes,
                    "所选文件与已验证的内容不一致。")
                // Independent saved-file readback catches staging faults before export.
                demand(sourceHash(output, entry.size, control, "回读所选文件") == entry.sha256,
                    "保存后的文件未通过回读校验。")
                diskPolicy.requireAdditional(directory, 0)
                control.check()
                keep = true
                output
            } finally { if (!keep) output.delete() }
        }
    }

    private fun checkedName(name: String) {
        safeFilename(name)
        demand(utf8(name).size in 1..180, "多文件包中的原文件名不得超过 180 个 UTF-8 字节。")
    }

    /**
     * Conservative raw-DEFLATE bound plus the profile's largest names/headers, capped at
     * the archive admission limit. This is a workspace estimate, not a reservation or
     * a claim about the eventual compressed length. The raw bound follows zlib's
     * deflateBound conservative fixed-block formula, with the larger per-stream constant:
     * https://github.com/madler/zlib/blob/develop/deflate.c
     */
    fun plannedArchiveBytes(totalBytes: Long, count: Int, maxArchiveBytes: Long): Long {
        demand(totalBytes >= 0 && count in 1..100 && maxArchiveBytes > 0, "多文件工作空间预算无效。")
        val cap = minOf(maxArchiveBytes, MAX_ZIP32)
        var size = minOf(totalBytes, cap)
        // Per member: 30+185 local header/name, 16 descriptor, 46+185 central header/name,
        // and 7 conservative raw-DEFLATE overhead bytes. EOCD+marker occupy 41 bytes.
        for (additional in listOf(totalBytes / 8, totalBytes / 256, totalBytes / 512,
                count * 469L + 22 + markerBytes.size)) {
            size += minOf(additional, cap - size)
        }
        return size
    }

    private fun budgets(total: Long, archive: Long) {
        demand(total > 0 && archive > 0, "多文件处理预算无效。")
    }

    private fun addSize(total: Long, size: Long, limit: Long): Long {
        demand(size >= 0 && size <= limit && total <= limit - size, "多文件原始总大小超过处理预算。")
        return total + size
    }

    private fun snapshot(file: File): Snapshot {
        val attributes = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        demand(attributes.isRegularFile && !attributes.isSymbolicLink, "多文件任务只接受普通文件。")
        return Snapshot(file, attributes.size(), attributes.lastModifiedTime().toMillis(), attributes.fileKey())
    }

    private fun unchanged(previous: Snapshot) {
        val next = snapshot(previous.file)
        demand(previous == next, CHANGED_ERROR)
    }

    private fun sourceHash(file: File, expected: Long, control: Control, stage: String, output: OutputStream? = null): String {
        val buffer = ByteArray(CHUNK)
        val digest = MessageDigest.getInstance("SHA-256")
        var read = 0L
        try {
            file.inputStream().use { input ->
                while (true) {
                    control.check()
                    val count = input.read(buffer, 0, minOf(CHUNK.toLong(), expected - read + 1).toInt())
                    if (count < 0) break
                    demand(count > 0 && read + count <= expected, CHANGED_ERROR)
                    digest.update(buffer, 0, count)
                    output?.write(buffer, 0, count)
                    read += count
                    control.report(stage, minOf(read, Int.MAX_VALUE.toLong()).toInt(), minOf(expected, Int.MAX_VALUE.toLong()).toInt())
                }
            }
            demand(read == expected, CHANGED_ERROR)
            return digest.digest().hex()
        } finally { buffer.fill(0) }
    }

    private class LimitedOutput(private val target: OutputStream, private val maximum: Long,
                                private val directory: File, private val diskPolicy: BundleDiskPolicy,
                                private val planned: Long) : OutputStream() {
        private var size = 0L
        override fun write(b: Int) {
            demand(size < maximum, "多文件包超过容器字节预算。")
            diskPolicy.requireAdditional(directory, maxOf(1L, planned - size))
            target.write(b); size++
        }
        override fun write(b: ByteArray, offset: Int, length: Int) {
            demand(length.toLong() <= maximum - size, "多文件包超过容器字节预算。")
            diskPolicy.requireAdditional(directory, maxOf(length.toLong(), planned - size))
            target.write(b, offset, length); size += length
        }
        override fun flush() = target.flush()
    }

    /** Bounds all metadata before any decompressor is constructed. */
    private fun readDirectory(input: RandomAccessFile, maxTotal: Long, maxArchive: Long, control: Control): Directory? {
        val length = input.length()
        if (length < markerBytes.size) return null
        input.seek(length - markerBytes.size)
        if (!exact(input, markerBytes.size).contentEquals(markerBytes)) return null
        val eocdOffset = length - 22 - markerBytes.size
        val footer = if (eocdOffset >= 0) {
            input.seek(eocdOffset); exact(input, 22)
        } else byteArrayOf()
        if (footer.size != 22 || u32(footer, 0) != 0x06054b50L) {
            // The suffix may belong to an ordinary ZIP's longer comment or to a
            // text file. Neither opts into automatic member extraction.
            if (hasDifferentZipComment(input, length, control)) return null
            input.seek(0)
            if (u32(exact(input, 4), 0) != 0x04034b50L) return null
            throw StegException(PROFILE_ERROR)
        }
        demand(length <= minOf(maxArchive, MAX_ZIP32), "多文件包超过容器字节预算。")
        demand(u32(footer, 0) == 0x06054b50L && u16(footer, 4) == 0 && u16(footer, 6) == 0 &&
            u16(footer, 8) == u16(footer, 10) && u16(footer, 10) in 1..100 &&
            u16(footer, 20) == markerBytes.size, PROFILE_ERROR)
        val count = u16(footer, 10)
        val centralSize = u32(footer, 12)
        val centralOffset = u32(footer, 16)
        demand(centralSize in (46L * count)..CENTRAL_LIMIT.toLong() && centralOffset <= eocdOffset &&
            centralOffset + centralSize == eocdOffset, PROFILE_ERROR)
        input.seek(centralOffset)
        val central = exact(input, centralSize.toInt())
        val records = ArrayList<Record>(count)
        var offset = 0
        var expanded = 0L
        for (index in 1..count) {
            control.check()
            demand(offset + 46 <= central.size && u32(central, offset) == 0x02014b50L, PROFILE_ERROR)
            val flags = u16(central, offset + 8)
            val method = u16(central, offset + 10)
            val nameLength = u16(central, offset + 28)
            val attrs = u32(central, offset + 38)
            val type = (attrs ushr 16).toInt() and 0xf000
            demand(u16(central, offset + 6) in 10..20 && flags and 0x0800 != 0 &&
                flags and 0x0808.inv() == 0 && method in setOf(0, 8) && nameLength in 6..185 &&
                u16(central, offset + 30) == 0 && u16(central, offset + 32) == 0 &&
                u16(central, offset + 34) == 0 && attrs and 0x18L == 0L &&
                type in setOf(0, 0x8000) && offset + 46 + nameLength <= central.size, PROFILE_ERROR)
            val rawName = central.copyOfRange(offset + 46, offset + 46 + nameLength)
            val path = decodeUtf8(rawName)
            val prefix = "%04d/".format(java.util.Locale.ROOT, index)
            demand(path.startsWith(prefix), PROFILE_ERROR)
            val name = path.substring(prefix.length)
            checkedName(name)
            val size = u32(central, offset + 24)
            val compressed = u32(central, offset + 20)
            val localOffset = u32(central, offset + 42)
            demand(size != 0xffffffffL && compressed != 0xffffffffL && compressed <= maxArchive &&
                localOffset < centralOffset && (method != 0 || size == compressed), PROFILE_ERROR)
            expanded = addSize(expanded, size, maxTotal)
            records += Record(index, name, rawName, u16(central, offset + 6), flags, method,
                u16(central, offset + 12), u16(central, offset + 14), u32(central, offset + 16), compressed, size, localOffset)
            offset += 46 + nameLength
        }
        demand(offset == central.size && records.first().localOffset == 0L, PROFILE_ERROR)
        for ((at, record) in records.withIndex()) {
            control.check()
            val next = records.getOrNull(at + 1)?.localOffset ?: centralOffset
            demand(record.localOffset + 30 <= next && next <= centralOffset, PROFILE_ERROR)
            input.seek(record.localOffset)
            val header = exact(input, 30)
            demand(u32(header, 0) == 0x04034b50L && u16(header, 4) == record.version &&
                u16(header, 6) == record.flags && u16(header, 8) == record.method &&
                u16(header, 10) == record.time && u16(header, 12) == record.date &&
                u16(header, 26) == record.path.size && u16(header, 28) == 0, PROFILE_ERROR)
            record.dataOffset = record.localOffset + 30 + record.path.size
            val dataEnd = record.dataOffset + record.compressed
            demand(dataEnd <= next && exact(input, record.path.size).contentEquals(record.path), PROFILE_ERROR)
            if (record.flags and 8 == 0) {
                demand(u32(header, 14) == record.crc && u32(header, 18) == record.compressed &&
                    u32(header, 22) == record.size && dataEnd == next, PROFILE_ERROR)
            } else {
                val allZero = u32(header, 14) == 0L && u32(header, 18) == 0L && u32(header, 22) == 0L
                val allMatch = u32(header, 14) == record.crc && u32(header, 18) == record.compressed &&
                    u32(header, 22) == record.size
                demand(allZero || allMatch, PROFILE_ERROR)
                val descriptorSize = next - dataEnd
                demand(descriptorSize == 12L || descriptorSize == 16L, PROFILE_ERROR)
                input.seek(dataEnd)
                val descriptor = exact(input, descriptorSize.toInt())
                val atValue = if (descriptorSize == 16L) 4 else 0
                demand((atValue == 0 || u32(descriptor, 0) == 0x08074b50L) &&
                    u32(descriptor, atValue) == record.crc && u32(descriptor, atValue + 4) == record.compressed &&
                    u32(descriptor, atValue + 8) == record.size, PROFILE_ERROR)
            }
        }
        demand(input.length() == length, CHANGED_ERROR)
        return Directory(records, length, expanded)
    }

    /** A bounded footer probe only; ordinary ZIPs may use features outside this profile. */
    private fun hasDifferentZipComment(input: RandomAccessFile, length: Long, control: Control): Boolean {
        val size = minOf(length, 65535L + 22).toInt()
        val tail = ByteArray(size)
        input.seek(length - size)
        val first = minOf(CHUNK, size)
        input.readFully(tail, 0, first)
        if (size > first) input.readFully(tail, first, size - first)
        for (offset in 0..(size - 22)) {
            if (offset % 1024 == 0) control.check()
            if (u32(tail, offset) == 0x06054b50L) {
                val commentSize = u16(tail, offset + 20)
                if (offset + 22 + commentSize == size && commentSize != markerBytes.size) return true
            }
        }
        control.check()
        return false
    }

    /** Uses the same opened handle as the bounded directory parser. */
    private fun readEntry(input: RandomAccessFile, record: Record, control: Control,
                          stage: String, output: OutputStream? = null): String {
        val buffer = ByteArray(CHUNK)
        val plain = if (record.method == 8) ByteArray(CHUNK) else buffer
        val inflater = if (record.method == 8) Inflater(true) else null
        val digest = MessageDigest.getInstance("SHA-256")
        val crc = CRC32()
        var remaining = record.compressed
        var produced = 0L
        fun consume(bytes: ByteArray, count: Int) {
            demand(produced + count <= record.size, "多文件包展开长度不符或超过处理预算。")
            digest.update(bytes, 0, count); crc.update(bytes, 0, count)
            output?.write(bytes, 0, count)
            produced += count
            control.report(stage, minOf(produced, Int.MAX_VALUE.toLong()).toInt(), minOf(record.size, Int.MAX_VALUE.toLong()).toInt())
        }
        try {
            input.seek(record.dataOffset)
            if (inflater == null) {
                while (remaining > 0) {
                    control.check()
                    val count = minOf(CHUNK.toLong(), remaining).toInt()
                    input.readFully(buffer, 0, count); remaining -= count
                    consume(buffer, count)
                }
            } else {
                while (!inflater.finished()) {
                    control.check()
                    if (inflater.needsInput()) {
                        demand(remaining > 0, "多文件包压缩数据不完整。")
                        val count = minOf(CHUNK.toLong(), remaining).toInt()
                        input.readFully(buffer, 0, count); remaining -= count
                        inflater.setInput(buffer, 0, count)
                    }
                    val count = inflater.inflate(plain)
                    if (count > 0) consume(plain, count)
                    else demand(inflater.finished() || inflater.needsInput(), "多文件包压缩数据无效。")
                }
                demand(remaining == 0L && inflater.remaining == 0, "多文件包压缩成员含额外数据。")
            }
            demand(produced == record.size && crc.value == record.crc, "多文件包未通过长度或 CRC 校验。")
            control.check()
            return digest.digest().hex()
        } finally { inflater?.end(); buffer.fill(0); plain.fill(0) }
    }

    private fun exact(input: RandomAccessFile, size: Int): ByteArray = ByteArray(size).also { input.readFully(it) }
    private fun u16(bytes: ByteArray, at: Int): Int = (bytes[at].toInt() and 255) or ((bytes[at + 1].toInt() and 255) shl 8)
    private fun u32(bytes: ByteArray, at: Int): Long = u16(bytes, at).toLong() or (u16(bytes, at + 2).toLong() shl 16)
    private inline fun <T> translated(diskPolicy: BundleDiskPolicy = BundleDiskPolicy(), action: () -> T): T = try { action() }
    catch (e: StegException) { throw e }
    catch (e: IOException) { throw diskPolicy.mapFailure(e) }
    catch (e: java.util.zip.DataFormatException) { throw StegException("多文件包压缩数据无效。", e) }
    catch (e: SecurityException) { throw StegException("无法访问多文件包或所选文件。", e) }
}
