package com.moyle.steg.android

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import com.moyle.steg.core.CancelledException
import com.moyle.steg.core.Control
import com.moyle.steg.core.StegException
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.io.FileNotFoundException
import java.io.InputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.security.MessageDigest

/** External documents use real descriptors and files generated in bounded chunks. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class LargeDocumentStoreTest {
    private lateinit var app: Application
    private lateinit var source: File
    private lateinit var destination: File
    private lateinit var provider: LargeDocumentsProvider
    private lateinit var store: DocumentStore
    private var available = Long.MAX_VALUE
    private val uri = Uri.parse("content://large-documents.test/document/source")
    private val destinationUri = Uri.parse("content://large-documents.test/document/output")
    private val document get() = PickedDocument(uri, "source.bin")

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        source = File.createTempFile("large-source-", ".bin", app.cacheDir)
        destination = File.createTempFile("large-destination-", ".bin", app.cacheDir)
        provider = LargeDocumentsProvider(source, destination)
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "large-documents.test"
            packageName = app.packageName
            name = LargeDocumentsProvider::class.java.name
            applicationInfo = app.applicationInfo
            exported = true
            grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("large-documents.test", provider)
        store = DocumentStore(app, privateSpace = { available })
    }

    @After fun teardown() {
        // Every path belongs to this Robolectric sandbox; source must be closed.
        assertTrue(!source.exists() || source.delete())
        assertTrue(!destination.exists() || destination.delete())
        store.workDirectory().listFiles()?.forEach { assertTrue(it.delete()) }
    }

    private fun rejects(fragment: String, action: () -> Unit): StegException {
        try { action() } catch (error: StegException) {
            assertTrue("unexpected error: ${error.message}", error.message.orEmpty().contains(fragment))
            return error
        }
        throw AssertionError("expected the document operation to reject this input")
    }

    private fun assertNoCapture() {
        assertTrue("failed capture left a private file", store.workDirectory().listFiles().orEmpty().isEmpty())
    }

    private fun writePattern(file: File, size: Long, value: Byte = 65) {
        val block = ByteArray(65536) { value }
        file.outputStream().use { output ->
            var left = size
            while (left > 0) {
                val count = minOf(left, block.size.toLong()).toInt()
                output.write(block, 0, count)
                left -= count
            }
        }
    }

    private fun hash(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val block = ByteArray(65536)
        file.inputStream().use { input ->
            while (true) {
                val count = input.read(block)
                if (count < 0) break
                digest.update(block, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
    }

    private fun pngHeader(width: Int, height: Int) = ByteBuffer.allocate(54)
        .put(byteArrayOf(-119, 80, 78, 71, 13, 10, 26, 10))
        .putInt(13).put("IHDR".toByteArray(Charsets.US_ASCII))
        .putInt(width).putInt(height).array()

    @Test fun probeUsesSignatureAndNeverReadsBeyond54Bytes() {
        val header = pngHeader(384, 256)
        source.writeBytes(header)
        provider.advertisedSize = 3L * 1024 * 1024 * 1024
        var read = 0
        var closed = false
        shadowOf(app.contentResolver).registerInputStream(uri, object : InputStream() {
            override fun read(): Int {
                check(read < 54) { "probe read beyond its signature budget" }
                return header[read++].toInt() and 255
            }
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                check(length <= 54 - read) { "probe requested bytes beyond its signature budget" }
                header.copyInto(bytes, offset, read, read + length)
                read += length
                return length
            }
            override fun close() { closed = true }
        })
        val result = store.probe(PickedDocument(uri, "renamed.jpg"), Control())
        assertEquals("png", result.format)
        assertEquals(384, result.width)
        assertEquals(256, result.height)
        assertEquals(3L * 1024 * 1024 * 1024, result.size)
        assertTrue(read in 24..54)
        assertTrue(closed)
        assertNoCapture()
    }

    @Test fun probeRecognizesGifAndSaesRegardlessOfSuffix() {
        source.writeBytes(byteArrayOf(71, 73, 70, 56, 57, 97, 64, 1, -56, 0))
        val gif = store.probe(PickedDocument(uri, "cover.png"), Control())
        assertEquals("gif", gif.format)
        assertEquals(320, gif.width)
        assertEquals(200, gif.height)
        source.writeBytes("SGAES001".toByteArray(Charsets.US_ASCII))
        val saes = store.probe(PickedDocument(uri, "encrypted.jpg"), Control())
        assertEquals("saes", saes.format)
        assertNull(saes.width)
        assertNull(saes.height)
        source.writeBytes(byteArrayOf(1, 2, 3))
        assertEquals("file", store.probe(PickedDocument(uri, "pretend.png"), Control()).format)
    }

    @Test fun probeDoesNotPresentInvalidPngDimensionsAsUsableEstimates() {
        source.writeBytes(pngHeader(0, 256))
        val result = store.probe(document, Control())
        assertEquals("png", result.format)
        assertNull(result.width)
        assertNull(result.height)
        source.writeBytes(pngHeader(Int.MIN_VALUE, 1))
        assertNull(store.probe(document, Control()).width)
    }

    @Test fun stableMultiChunkDocumentIsCapturedWithoutChangingSource() {
        val size = 12L * 1024 * 1024 + 17
        writePattern(source, size)
        val expected = hash(source)
        val progress = mutableListOf<Pair<Int, Int>>()
        val captured = store.captureFile(document, size, Control(progress = { stage, done, total ->
            if (stage == "读取文件") progress += done to total
        }))
        try {
            assertEquals(size, captured.length())
            assertEquals(expected, hash(captured))
            assertEquals(expected, hash(source))
            assertEquals(2, provider.sourceOpens)
            assertEquals(2, provider.queries)
            assertEquals(store.workDirectory().canonicalFile, captured.parentFile!!.canonicalFile)
            assertTrue(progress.size > 2)
            assertEquals(size.toInt() to size.toInt(), progress.last())
            assertTrue(progress.zipWithNext().all { (a, b) -> b.first > a.first && b.first - a.first <= 65536 })
        } finally { assertTrue(captured.delete()) }
    }

    @Test fun longMetadataOverBudgetIsRejectedBeforeOpeningSource() {
        provider.advertisedSize = Int.MAX_VALUE.toLong() + 1
        rejects("超过读取预算") { store.captureFile(document, 1024L * 1024 * 1024, Control()) }
        assertEquals(0, provider.sourceOpens)
        assertNoCapture()
    }

    @Test fun unknownSizeCannotBypassCaptureLimit() {
        provider.knownMetadata = false
        writePattern(source, 131073)
        val expected = hash(source)
        rejects("超过读取预算") { store.captureFile(document, 131072, Control()) }
        assertEquals(1, provider.sourceOpens)
        assertEquals(expected, hash(source))
        assertNoCapture()
    }

    @Test fun equalLengthRewriteWithRestoredMtimeIsRejected() {
        writePattern(source, 2L * 1024 * 1024)
        val modified = source.lastModified()
        var changed = false
        val control = Control(progress = { stage, done, _ ->
            if (stage == "读取文件" && done >= 65536 && !changed) {
                changed = true
                val block = ByteArray(65536) { 66 }
                RandomAccessFile(source, "rw").use { file -> repeat(32) { file.write(block) } }
                assertTrue(source.setLastModified(modified))
            }
        })
        rejects("文件发生变化") { store.captureFile(document, source.length(), control) }
        assertTrue(changed)
        assertEquals(2, provider.sourceOpens)
        assertNoCapture()
    }

    @Test fun metadataChangeAfterMatchingReadsStillRejectsCapture() {
        writePattern(source, 65537)
        provider.onQuery = { if (it == 2) provider.advertisedModified = source.lastModified() + 1000 }
        rejects("文件发生变化") { store.captureFile(document, source.length(), Control()) }
        assertNoCapture()
    }

    @Test fun providerThatCannotReopenRequiresStableLocalExport() {
        writePattern(source, 65537)
        provider.singleOpen = true
        rejects("完整保存到本机") { store.captureFile(document, source.length(), Control()) }
        assertEquals(2, provider.sourceOpens)
        assertNoCapture()
    }

    @Test fun cancellationDuringEachCapturePassRemovesPrivateFile() {
        writePattern(source, 200000)
        val expected = hash(source)
        for (cancelStage in listOf("读取文件", "核对输入一致性", "回读私有文件")) {
            var cancelled = false
            val error = rejects("已取消") {
                store.captureFile(document, source.length(), Control(
                    progress = { stage, _, _ -> if (stage == cancelStage) cancelled = true },
                    cancelled = { cancelled }
                ))
            }
            assertTrue(error is CancelledException)
            assertTrue("capture did not report $cancelStage", cancelled)
            assertNoCapture()
        }
        assertEquals(expected, hash(source))
    }

    @Test fun insufficientPrivateSpaceIsRejectedBeforeOpeningSource() {
        writePattern(source, 65537)
        available = source.length() + 32L * 1024 * 1024 - 1
        rejects("私有空间不足") { store.captureFile(document, source.length(), Control()) }
        assertEquals(0, provider.sourceOpens)
        assertNoCapture()
    }

    @Test fun fallingPrivateSpaceDuringUnknownSizeCaptureCleansPartialFile() {
        provider.knownMetadata = false
        writePattern(source, 200000)
        rejects("私有空间不足") {
            store.captureFile(document, source.length(), Control(progress = { stage, done, _ ->
                if (stage == "读取文件" && done >= 65536) available = 0
            }))
        }
        assertEquals(1, provider.sourceOpens)
        assertNoCapture()
    }

    @Test fun corruptPrivateCaptureIsCaughtByIndependentReadback() {
        writePattern(source, 200000)
        provider.onOpen = { open ->
            if (open == 2) {
                val captured = store.workDirectory().listFiles()!!.single()
                RandomAccessFile(captured, "rw").use { it.write(66) }
            }
        }
        rejects("私有工作文件保存后校验失败") { store.captureFile(document, source.length(), Control()) }
        assertNoCapture()
    }

    @Test fun exportCopiesBytesWithProgressAndVerifiesClosedOutput() {
        writePattern(source, 1024L * 1024 + 11)
        val expected = hash(source)
        val copied = mutableListOf<Pair<Int, Int>>()
        val checked = mutableListOf<Pair<Int, Int>>()
        store.export(source, destinationUri, listOf(uri), expected, Control(progress = { stage, done, total ->
            if (stage == "保存文件") copied += done to total
            if (stage == "回读验证") checked += done to total
        }))
        assertEquals(expected, hash(destination))
        assertEquals(source.length(), destination.length())
        assertTrue(copied.size > 2)
        assertTrue(checked.size > 2)
        assertEquals(source.length().toInt() to source.length().toInt(), copied.last())
        assertEquals(source.length().toInt() to source.length().toInt(), checked.last())
    }

    @Test fun exportRefusesExistingNonemptyDestination() {
        source.writeBytes(byteArrayOf(1, 2, 3))
        destination.writeBytes(byteArrayOf(9, 8, 7))
        rejects("不是新建空文件") { store.export(source, destinationUri, listOf(uri), hash(source), Control()) }
        assertArrayEquals(byteArrayOf(9, 8, 7), destination.readBytes())
        assertEquals(0, provider.destinationWrites)
    }

    @Test fun stagedValidationRejectsChangedBytesAndOverBudgetLongLength() {
        writePattern(source, 200000)
        val expected = hash(source)
        store.validateStaged(source, expected, Control())
        RandomAccessFile(source, "rw").use { it.write(66) }
        rejects("私有文件已改变") { store.validateStaged(source, expected, Control()) }
        val oversized = object : File(source.absolutePath) {
            override fun length() = 1024L * 1024 * 1024 + 1024 * 1024 + 1
        }
        rejects("超过") { store.validateStaged(oversized, expected, Control()) }
        assertEquals(0, provider.destinationWrites)
    }

    class LargeDocumentsProvider(private val source: File, private val destination: File) : ContentProvider() {
        var knownMetadata = true
        var advertisedSize: Long? = null
        var advertisedModified: Long? = null
        var singleOpen = false
        var sourceOpens = 0
        var destinationWrites = 0
        var queries = 0
        var onQuery: (Int) -> Unit = {}
        var onOpen: (Int) -> Unit = {}
        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            queries++
            onQuery(queries)
            val columns = projection?.map { it }?.toTypedArray() ?: arrayOf(OpenableColumns.SIZE)
            return MatrixCursor(columns).apply {
                addRow(columns.map<String, Any?> { column -> when (column) {
                    OpenableColumns.DISPLAY_NAME -> "source.bin"
                    OpenableColumns.SIZE -> if (knownMetadata) advertisedSize ?: source.length() else null
                    DocumentsContract.Document.COLUMN_LAST_MODIFIED -> if (knownMetadata) advertisedModified ?: source.lastModified() else null
                    else -> null
                } }.toTypedArray())
            }
        }
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            if (uri.lastPathSegment == "output") {
                if (mode != "r") destinationWrites++
                return ParcelFileDescriptor.open(destination, if (mode == "r") ParcelFileDescriptor.MODE_READ_ONLY
                    else ParcelFileDescriptor.MODE_WRITE_ONLY or ParcelFileDescriptor.MODE_TRUNCATE)
            }
            sourceOpens++
            check(mode == "r") { "source document must never be opened for writing" }
            onOpen(sourceOpens)
            if (singleOpen && sourceOpens > 1) throw FileNotFoundException("provider can only open once")
            return ParcelFileDescriptor.open(source, ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun getType(uri: Uri) = "application/octet-stream"
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    }
}
