package com.moyle.steg.android

import android.Manifest
import android.app.Application
import android.content.ContentProvider
import android.content.ContentUris
import android.content.ContentValues
import android.content.pm.PackageManager
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Environment
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.provider.OpenableColumns
import androidx.core.content.FileProvider
import com.moyle.steg.core.CancelledException
import com.moyle.steg.core.Control
import com.moyle.steg.core.StegException
import com.moyle.steg.core.sha256
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.shadows.ShadowContentResolver
import org.robolectric.shadows.ShadowEnvironment
import java.io.File
import java.io.FileNotFoundException
import java.io.RandomAccessFile
import java.security.MessageDigest

/** Real exporter, file bytes, ContentResolver and descriptors; only Android's media service is synthetic. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class DownloadsExporterTest {
    private lateinit var app: Application
    private lateinit var staged: File
    private lateinit var provider: DownloadsProvider
    private lateinit var exporter: DownloadsExporter
    private lateinit var directory: File
    private val legacyFiles = mutableListOf<File>()
    private val payload = ByteArray(200_000) { (it * 17).toByte() }

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        // Android puts public Download under this root. Robolectric defaults the two APIs to
        // unrelated "external-cache" / "external-files" sandboxes, so make the fixture faithful.
        ShadowEnvironment.setExternalStoragePublicDirectory(Environment.getExternalStorageDirectory().toPath())
        // A real Android process keeps the same storage root. Robolectric creates a new root per
        // test but can retain AndroidX's static path cache; the provider lifecycle clears that cache.
        val downloadsAuthority = "${app.packageName}.downloads"
        val downloadsInfo = app.packageManager.resolveContentProvider(downloadsAuthority, PackageManager.GET_META_DATA)
            ?: throw AssertionError("Download FileProvider is missing from the application manifest")
        val filesProvider = DownloadFileProvider().apply { attachInfo(app, downloadsInfo) }
        ShadowContentResolver.registerProviderInternal(downloadsAuthority, filesProvider)
        directory = File.createTempFile("downloads-test-", ".dir", app.cacheDir).apply {
            check(delete()); check(mkdir())
        }
        staged = File(directory, "staged.bin").apply { writeBytes(payload) }
        provider = DownloadsProvider(File(directory, "provider").apply { check(mkdir()) })
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "media"
            packageName = app.packageName
            name = DownloadsProvider::class.java.name
            applicationInfo = app.applicationInfo
            exported = true
            grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("media", provider)
        exporter = DownloadsExporter(app)
    }

    @After fun cleanup() {
        // These paths are private to this test and its Robolectric sandbox on H:.
        assertTrue(directory.deleteRecursively())
        legacyFiles.forEach { assertTrue(!it.exists() || it.delete()) }
    }

    private fun save(control: Control = Control(), name: String = "report.txt") =
        exporter.save(staged, name, "text/plain", sha256(payload), control)

    private fun rejected(action: () -> Unit): StegException {
        try { action() } catch (error: StegException) { return error }
        throw AssertionError("expected save to reject the operation")
    }

    @Test @Config(sdk = [29, 35]) fun publishesOnlyAfterIndependentReadbackAndUsesActualProviderName() {
        provider.actualName = "report (3).txt"
        val result = save()
        val row = provider.rows.getValue(result.uri)
        assertArrayEquals(payload, row.file.readBytes())
        assertEquals("report (3).txt", result.displayName)
        assertEquals("Download/report (3).txt", result.displayPath)
        assertEquals("text/plain", result.mime)
        assertEquals("content", result.uri.scheme)
        assertEquals(0, row.pending)
        assertEquals(listOf("insert-pending", "write", "read-pending", "publish"), provider.events)
        assertArrayEquals(payload, staged.readBytes())
        assertFalse(exporter.requiresLegacyPermission())
    }

    @Test fun twoSavesNeverReplaceTheExistingDownload() {
        val first = save()
        val second = save()
        assertNotEquals(first.uri, second.uri)
        assertNotEquals(first.displayName, second.displayName)
        assertArrayEquals(payload, provider.rows.getValue(first.uri).file.readBytes())
        assertArrayEquals(payload, provider.rows.getValue(second.uri).file.readBytes())
        assertTrue(provider.deleted.isEmpty())
    }

    @Test fun changedPrivateFileIsRejectedBeforeCreatingAnyDownload() {
        staged.writeText("tampered")
        rejected { save() }
        assertTrue(provider.events.isEmpty())
        assertEquals("tampered", staged.readText())
    }

    @Test fun unsafeNameIsRejectedBeforeCreatingAnyDownload() {
        rejected { save(name = "../report.txt") }
        assertTrue(provider.events.isEmpty())
        assertTrue(staged.exists())
    }

    @Test fun corruptOutputIsDeletedAndPrivateFileCanBeRetried() {
        provider.corruptOnRead = true
        rejected { save() }
        assertTrue(provider.rows.isEmpty())
        assertEquals(1, provider.deleted.size)
        assertFalse(provider.events.contains("publish"))
        assertArrayEquals(payload, staged.readBytes())
        provider.corruptOnRead = false
        assertEquals(0, provider.rows.getValue(save().uri).pending)
    }

    @Test fun truncatedOutputIsNeverPublished() {
        provider.truncateOnRead = true
        rejected { save() }
        assertTrue(provider.rows.isEmpty())
        assertFalse(provider.events.contains("publish"))
        assertArrayEquals(payload, staged.readBytes())
    }

    @Test fun cancellationDuringCopyDeletesOnlyTheNewPendingItem() {
        val first = save()
        val firstFile = provider.rows.getValue(first.uri).file
        var cancel = false
        val control = Control(progress = { stage, _, _ -> if (stage == "保存到 Download") cancel = true }, cancelled = { cancel })
        assertTrue(rejected { save(control) } is CancelledException)
        assertEquals(setOf(first.uri), provider.rows.keys)
        assertArrayEquals(payload, firstFile.readBytes())
        assertArrayEquals(payload, staged.readBytes())
    }

    @Test fun cancellationDuringReadbackDeletesThePendingItem() {
        var cancel = false
        provider.beforeRead = { cancel = true }
        assertTrue(rejected { save(Control(cancelled = { cancel })) } is CancelledException)
        assertTrue(provider.rows.isEmpty())
        assertTrue(staged.exists())
    }

    @Test fun cancellationAfterCommitDoesNotDeleteASuccessfullyPublishedDownload() {
        var cancel = false
        provider.afterPublish = { cancel = true }
        val result = save(Control(cancelled = { cancel }))
        assertEquals(0, provider.rows.getValue(result.uri).pending)
        assertArrayEquals(payload, provider.rows.getValue(result.uri).file.readBytes())
        assertTrue(provider.deleted.isEmpty())
    }

    @Test fun failedPublishIsCleanedUpAndDoesNotClaimSuccess() {
        provider.refusePublish = true
        rejected { save() }
        assertTrue(provider.rows.isEmpty())
        assertTrue(staged.exists())
    }

    @Test fun outputThatCannotBeOpenedIsDeleted() {
        provider.refuseWrite = true
        rejected { save() }
        assertTrue(provider.rows.isEmpty())
        assertTrue(staged.exists())
    }

    @Test fun missingRealNamePreventsPublication() {
        provider.omitName = true
        rejected { save() }
        assertTrue(provider.rows.isEmpty())
        assertFalse(provider.events.contains("publish"))
    }

    @Test fun emptyAuthenticatedFileCanBePublished() {
        staged.writeBytes(byteArrayOf())
        val result = exporter.save(staged, "empty.txt", "text/plain", sha256(byteArrayOf()), Control())
        assertEquals(0L, provider.rows.getValue(result.uri).file.length())
        assertEquals(0, provider.rows.getValue(result.uri).pending)
    }

    @Test fun fullOneGiBFileIsCopiedAndVerifiedInBoundedChunks() {
        val size = 1024L * 1024 * 1024
        RandomAccessFile(staged, "rw").use { it.setLength(0); it.setLength(size) }
        fun hash(file: File): String {
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
        val expected = hash(staged)
        var copyReports = 0
        val control = Control(progress = { stage, completed, total ->
            assertTrue(completed >= 0)
            assertTrue(total >= completed)
            if (stage == "保存到 Download") copyReports++
        })
        val result = exporter.save(staged, "large.bin", "application/octet-stream", expected, control)
        val saved = provider.rows.getValue(result.uri)
        assertEquals(size, saved.file.length())
        assertEquals(expected, hash(saved.file))
        assertEquals(0, saved.pending)
        assertTrue("large output must remain cancellable between chunks", copyReports > 100)
        assertEquals(size, staged.length())
    }

    @Test @Config(sdk = [28]) fun oldAndroidRequestsPermissionBeforeAnyPublicWrite() {
        shadowOf(app).denyPermissions(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        assertTrue(exporter.requiresLegacyPermission())
        assertTrue(rejected { save() } is DownloadPermissionException)
        assertArrayEquals(payload, staged.readBytes())
        assertTrue(provider.events.isEmpty())
    }

    @Test @Config(sdk = [28], shadows = [HostFileProviderPaths::class])
    fun oldAndroidCreatesNumberedDownloadsAndReturnsShareableUris() {
        shadowOf(app).grantPermissions(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        check(downloads.isDirectory || downloads.mkdirs())
        val unique = "moyle-test-${System.nanoTime()}"
        val existing = File(downloads, "$unique.txt").also { legacyFiles += it; it.writeText("keep me") }
        val first = save(name = "$unique.txt")
        val firstFile = File(downloads, first.displayName).also { legacyFiles += it }
        val second = save(name = "$unique.txt")
        val secondFile = File(downloads, second.displayName).also { legacyFiles += it }
        assertEquals("$unique (1).txt", first.displayName)
        assertEquals("$unique (2).txt", second.displayName)
        assertEquals("Download/${first.displayName}", first.displayPath)
        assertEquals("content", first.uri.scheme)
        assertEquals("${app.packageName}.downloads", first.uri.authority)
        assertArrayEquals(payload, firstFile.readBytes())
        assertArrayEquals(payload, secondFile.readBytes())
        assertEquals("keep me", existing.readText())
        assertArrayEquals(payload, staged.readBytes())
        assertFalse(exporter.requiresLegacyPermission())
    }

    @Test @Config(sdk = [28], shadows = [HostFileProviderPaths::class])
    fun legacyProviderAllowsReadButRejectsEveryWriteModeAndFilesOutsideDownload() {
        shadowOf(app).grantPermissions(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        val result = save(name = "moyle-readonly-${System.nanoTime()}.txt")
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val saved = File(downloads, result.displayName).also { legacyFiles += it }
        val readback = app.contentResolver.openInputStream(result.uri)!!.use { it.readBytes() }
        assertArrayEquals(payload, readback)
        for (mode in listOf("w", "wt", "wa", "rw", "rwt")) {
            assertThrows(FileNotFoundException::class.java) {
                app.contentResolver.openFileDescriptor(result.uri, mode)?.close()
            }
        }
        assertArrayEquals(payload, saved.readBytes())
        val sibling = File(Environment.getExternalStorageDirectory(), "DownloadSibling-${System.nanoTime()}")
            .apply { check(mkdir()) }
        val outside = File(sibling, "keep.txt").apply { writeText("keep me") }
        legacyFiles += outside
        legacyFiles += sibling
        assertThrows(IllegalArgumentException::class.java) {
            FileProvider.getUriForFile(app, "${app.packageName}.downloads", outside)
        }
        assertEquals("keep me", outside.readText())
    }

    @Test @Config(sdk = [28]) fun oldAndroidCancellationRemovesOnlyItsOwnPartialFile() {
        shadowOf(app).grantPermissions(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        check(downloads.isDirectory || downloads.mkdirs())
        val unique = "moyle-cancel-${System.nanoTime()}"
        val existing = File(downloads, "$unique.txt").also { legacyFiles += it; it.writeText("keep me") }
        var cancel = false
        val control = Control(progress = { stage, _, _ -> if (stage == "保存到 Download") cancel = true }, cancelled = { cancel })
        assertTrue(rejected { save(control, "$unique.txt") } is CancelledException)
        assertEquals(listOf(existing.name), downloads.listFiles().orEmpty().filter { it.name.startsWith(unique) }.map { it.name })
        assertEquals("keep me", existing.readText())
        assertArrayEquals(payload, staged.readBytes())
    }

    /**
     * AndroidX uses '/' when checking canonical Android paths. JVM File uses '\\' on Windows.
     * Adapt only this separator-dependent library predicate; real FileProvider URI parsing,
     * manifest configuration and DownloadFileProvider read-only enforcement remain exercised.
     */
    @Implements(className = "androidx.core.content.FileProvider\$SimplePathStrategy", isInAndroidSdk = false)
    class HostFileProviderPaths {
        @Implementation
        protected fun belongsToRoot(filePath: String, rootPath: String): Boolean {
            val file = File(filePath).toPath().normalize()
            val root = File(rootPath).toPath().normalize()
            return file != root && file.startsWith(root)
        }
    }

    class DownloadsProvider(private val directory: File) : ContentProvider() {
        data class Row(val file: File, val name: String, val mime: String, var pending: Int = 1)
        val rows = linkedMapOf<Uri, Row>()
        val events = mutableListOf<String>()
        val deleted = mutableListOf<Uri>()
        var actualName: String? = null
        var corruptOnRead = false
        var truncateOnRead = false
        var refusePublish = false
        var refuseWrite = false
        var omitName = false
        var beforeRead: () -> Unit = {}
        var afterPublish: () -> Unit = {}
        private var nextId = 1L

        override fun onCreate() = true
        override fun getType(uri: Uri) = rows[uri]?.mime ?: "application/octet-stream"
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            assertEquals(MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), uri)
            val incoming = requireNotNull(values)
            assertEquals(1, incoming.getAsInteger(MediaStore.MediaColumns.IS_PENDING))
            assertEquals(Environment.DIRECTORY_DOWNLOADS + "/", incoming.getAsString(MediaStore.MediaColumns.RELATIVE_PATH))
            val id = nextId++
            val destination = ContentUris.withAppendedId(uri, id)
            val requested = incoming.getAsString(MediaStore.MediaColumns.DISPLAY_NAME)
            val actual = actualName ?: if (id == 1L) requested else "report (${id - 1}).txt"
            val file = File(directory, "row-$id").apply { check(createNewFile()) }
            rows[destination] = Row(file, actual, incoming.getAsString(MediaStore.MediaColumns.MIME_TYPE))
            events += "insert-pending"
            return destination
        }

        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            val row = rows[uri] ?: throw FileNotFoundException(uri.toString())
            val columns = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE, MediaStore.MediaColumns.RELATIVE_PATH)
            return MatrixCursor(columns).apply {
                val cells: List<Any?> = columns.map { column -> when (column) {
                    OpenableColumns.DISPLAY_NAME -> if (omitName) null else row.name
                    OpenableColumns.SIZE -> row.file.length()
                    MediaStore.MediaColumns.RELATIVE_PATH -> "Download/"
                    MediaStore.MediaColumns.MIME_TYPE -> row.mime
                    MediaStore.MediaColumns.IS_PENDING -> row.pending
                    else -> null
                } }
                addRow(cells.toTypedArray())
            }
        }

        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            val row = rows[uri] ?: throw FileNotFoundException(uri.toString())
            assertEquals("unverified output was published early", 1, row.pending)
            if (mode.contains('w')) {
                if (refuseWrite) throw FileNotFoundException("synthetic write denied")
                events += "write"
                return ParcelFileDescriptor.open(row.file, ParcelFileDescriptor.MODE_WRITE_ONLY or ParcelFileDescriptor.MODE_TRUNCATE)
            }
            events += "read-pending"
            if (corruptOnRead) RandomAccessFile(row.file, "rw").use { it.write(99) }
            if (truncateOnRead) RandomAccessFile(row.file, "rw").use { it.setLength(17) }
            beforeRead()
            return ParcelFileDescriptor.open(row.file, ParcelFileDescriptor.MODE_READ_ONLY)
        }

        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int {
            assertEquals(0, values?.getAsInteger(MediaStore.MediaColumns.IS_PENDING))
            if (refusePublish) return 0
            rows.getValue(uri).pending = 0
            events += "publish"
            afterPublish()
            return 1
        }

        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int {
            val row = rows.remove(uri) ?: return 0
            assertEquals("a published download must never be revoked by cancellation", 1, row.pending)
            assertTrue(row.file.delete())
            deleted += uri
            return 1
        }
    }
}
