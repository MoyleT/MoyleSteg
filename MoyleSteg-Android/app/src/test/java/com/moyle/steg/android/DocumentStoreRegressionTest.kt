package com.moyle.steg.android

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
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.io.FileNotFoundException
import java.io.RandomAccessFile

/** Real DocumentStore and ContentResolver reads; only the external provider is controlled. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class DocumentStoreRegressionTest {
    private lateinit var source: File
    private lateinit var provider: SyntheticDocuments
    private lateinit var store: DocumentStore
    private val uri = Uri.parse("content://capture.test/source.bin")
    private val document get() = PickedDocument(uri, "source.bin")

    @Before fun setup() {
        val app = RuntimeEnvironment.getApplication()
        // Robolectric's app cache follows its test sandbox, rooted in java.io.tmpdir.
        source = File.createTempFile("capture-source-", ".bin", app.cacheDir)
        provider = SyntheticDocuments(source)
        // Registration routes queries, but the real file-open transport also needs
        // the context and authority normally installed by Android's provider lifecycle.
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "capture.test"
            packageName = app.packageName
            name = SyntheticDocuments::class.java.name
            applicationInfo = app.applicationInfo
            exported = true
            grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("capture.test", provider)
        store = DocumentStore(app)
    }

    @After fun teardown() {
        // Delete only this test's own synthetic file, never an external provider file.
        assertTrue("a captured file descriptor was left open", !source.exists() || source.delete())
    }

    private fun rejects(fragment: String, action: () -> Unit): StegException {
        try { action() } catch (error: StegException) {
            assertTrue("unexpected error: ${error.message}", error.message.orEmpty().contains(fragment))
            return error
        }
        throw AssertionError("expected DocumentStore.capture to reject this input")
    }

    @Test fun stableDocumentIsReadTwiceThroughRealFileDescriptors() {
        val expected = ByteArray(200000) { (it * 17).toByte() }
        source.writeBytes(expected)
        val captured = store.capture(document, expected.size, Control())
        assertArrayEquals(expected, captured)
        assertEquals(2, provider.opens)
        assertEquals("metadata must be checked before and after capture", 2, provider.queries)
        assertArrayEquals(expected, source.readBytes())
        captured.fill(0)
    }

    @Test fun equalLengthRewriteWithRestoredMtimeRejectsMixedCapture() {
        rejectConcurrentRewrite(knownMetadata = true)
    }

    @Test fun unknownMetadataDoesNotBypassContentComparison() {
        rejectConcurrentRewrite(knownMetadata = false)
    }

    private fun rejectConcurrentRewrite(knownMetadata: Boolean) {
        provider.knownMetadata = knownMetadata
        val size = 2 * 1024 * 1024
        source.writeBytes(ByteArray(size) { 65 })
        val originalMtime = source.lastModified()
        var changed = false
        val control = Control(progress = { stage, completed, _ ->
            if (stage == "读取文件" && completed >= 65536 && !changed) {
                changed = true
                RandomAccessFile(source, "rw").use { it.write(ByteArray(size) { 66 }) }
                assertTrue("synthetic timestamp could not be restored", source.setLastModified(originalMtime))
                assertEquals(originalMtime, source.lastModified())
            }
        })
        rejects("文件发生变化") { store.capture(document, size, control) }
        assertTrue("the public first-chunk callback did not run", changed)
        assertEquals(2, provider.opens)
        assertTrue(source.readBytes().all { it == 66.toByte() })
    }

    @Test fun metadataOverBudgetIsRejectedBeforeOpeningAnyFileDescriptor() {
        source.writeBytes(ByteArray(32) { 65 })
        provider.advertisedSize = 4097
        rejects("超过读取预算") { store.capture(document, 4096, Control()) }
        assertEquals(0, provider.opens)
        assertEquals(1, provider.queries)
        assertEquals(32, source.length().toInt())
    }

    @Test fun unknownMetadataStillSupportsStableInput() {
        provider.knownMetadata = false
        val expected = ByteArray(65537) { (it * 13).toByte() }
        source.writeBytes(expected)
        val captured = store.capture(document, expected.size, Control())
        assertArrayEquals(expected, captured)
        assertEquals(2, provider.opens)
        captured.fill(0)
    }

    @Test fun unknownSizeCannotBypassActualReadBudget() {
        provider.knownMetadata = false
        source.writeBytes(ByteArray(4097) { 65 })
        rejects("超过读取预算") { store.capture(document, 4096, Control()) }
        assertEquals(1, provider.opens)
    }

    @Test fun providerWhichOnlyOpensOnceIsRejectedWithLocalExportAdvice() {
        source.writeBytes(ByteArray(64) { 65 })
        provider.singleOpen = true
        rejects("完整保存到本机") { store.capture(document, 64, Control()) }
        assertEquals(2, provider.opens)
        assertEquals(64, source.length().toInt())
    }

    @Test fun providerWithoutModifiedColumnCanFallBackToSizeMetadata() {
        source.writeBytes(ByteArray(64) { 65 })
        provider.unsupportedModifiedColumn = true
        val captured = store.capture(document, 64, Control())
        assertArrayEquals(ByteArray(64) { 65 }, captured)
        assertEquals(2, provider.opens)
        assertEquals("both metadata observations should use the size-only fallback", 4, provider.queries)
        captured.fill(0)
    }

    @Test fun observedMetadataChangeAfterMatchingReadsStillRejectsInput() {
        source.writeBytes(ByteArray(64) { 65 })
        provider.onQuery = { query ->
            if (query == 2) provider.advertisedModified = source.lastModified() + 1000
        }
        rejects("文件发生变化") { store.capture(document, 64, Control()) }
        assertEquals(2, provider.opens)
        assertEquals(2, provider.queries)
    }

    @Test fun cancellingComparisonClosesTheRealInputAndPreservesSource() {
        val expected = ByteArray(200000) { 65 }
        source.writeBytes(expected)
        var cancelled = false
        val control = Control(progress = { stage, _, _ ->
            if (stage == "核对输入一致性") cancelled = true
        }, cancelled = { cancelled })
        val error = rejects("已取消") { store.capture(document, expected.size, control) }
        assertTrue(error is CancelledException)
        assertTrue(cancelled)
        assertEquals(2, provider.opens)
        assertArrayEquals(expected, source.readBytes())
    }

    @Test fun cancellationBeforeCaptureDoesNotQueryOrOpenProvider() {
        rejects("已取消") { store.capture(document, 64, Control(cancelled = { true })) }
        assertEquals(0, provider.queries)
        assertEquals(0, provider.opens)
    }

    class SyntheticDocuments(private val source: File) : ContentProvider() {
        var knownMetadata = true
        var advertisedSize: Long? = null
        var advertisedModified: Long? = null
        var singleOpen = false
        var unsupportedModifiedColumn = false
        var opens = 0
        var queries = 0
        var onQuery: (Int) -> Unit = {}

        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            queries++
            onQuery(queries)
            val columns = projection?.map { it }?.toTypedArray() ?: arrayOf(
                OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED
            )
            if (unsupportedModifiedColumn && DocumentsContract.Document.COLUMN_LAST_MODIFIED in columns)
                throw IllegalArgumentException("synthetic provider has no modified column")
            return MatrixCursor(columns).apply {
                addRow(columns.map<String, Any?> { column ->
                    when (column) {
                        OpenableColumns.DISPLAY_NAME -> "source.bin"
                        OpenableColumns.SIZE -> if (knownMetadata) advertisedSize ?: source.length() else null
                        DocumentsContract.Document.COLUMN_LAST_MODIFIED -> if (knownMetadata) advertisedModified ?: source.lastModified() else null
                        else -> null
                    }
                }.toTypedArray())
            }
        }
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            opens++
            check(mode == "r") { "capture must never request a writable provider descriptor" }
            if (singleOpen && opens > 1) throw FileNotFoundException("synthetic provider can only open once")
            return ParcelFileDescriptor.open(source, ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun getType(uri: Uri) = "application/octet-stream"
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    }
}
