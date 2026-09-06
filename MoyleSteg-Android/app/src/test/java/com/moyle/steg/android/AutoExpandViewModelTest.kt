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
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.Credential
import com.moyle.steg.core.Limits
import com.moyle.steg.core.PngCodec
import com.moyle.steg.core.Preflight
import com.moyle.steg.core.RgbaImage
import com.moyle.steg.core.StegEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
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
import java.util.Random
import java.util.concurrent.TimeUnit

/** Real ViewModel, document capture, capacity planning, staging, and PNG recovery. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class AutoExpandViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var vm: MoyleViewModel
    private lateinit var provider: SyntheticDocuments
    private lateinit var directory: File
    private val expectedPayload = ByteArray(1024).also { Random(703L).nextBytes(it) }
    private val originalFiles = mutableMapOf<String, ByteArray>()

    @Before fun setup() {
        Dispatchers.setMain(dispatcher)
        val app = RuntimeEnvironment.getApplication()
        directory = File.createTempFile("autoexpand-", ".test", app.cacheDir)
        check(directory.delete() && directory.mkdir())
        provider = SyntheticDocuments(directory)
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "autoexpand.test"
            packageName = app.packageName
            name = SyntheticDocuments::class.java.name
            applicationInfo = app.applicationInfo
            exported = true
            grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("autoexpand.test", provider)
        writeSynthetic("payload.bin", expectedPayload)
        writeSynthetic("small.png", cover(16, 16))
        writeSynthetic("large.png", cover(96, 96))
        writeSynthetic("synthetic.stegkey", Credential.exportKey(ByteArray(32) { it.toByte() }))
        vm = MoyleViewModel(app)
    }

    @After fun teardown() {
        try {
            vm.viewModelScope.cancel()
            dispatcher.scheduler.runCurrent()
            vm.clearResult()
            assertTrue("the provider must never receive a write request", provider.writeRequests == 0)
            originalFiles.forEach { (name, bytes) ->
                assertArrayEquals("source was changed: $name", bytes, File(directory, name).readBytes())
            }
        } finally {
            Dispatchers.resetMain()
            // This directory was created solely for this test under its Robolectric sandbox.
            directory.listFiles()?.forEach { assertTrue("synthetic file still open", it.delete()) }
            assertTrue(directory.delete())
        }
    }

    private fun writeSynthetic(name: String, bytes: ByteArray) {
        File(directory, name).writeBytes(bytes)
        originalFiles[name] = bytes.copyOf()
    }

    private fun cover(width: Int, height: Int): ByteArray {
        val raw = ByteArray(width * height * 4) { index ->
            if (index % 4 == 3) 255.toByte() else (index * 37).toByte()
        }
        return PngCodec.encode(RgbaImage(width, height, raw))
    }

    private fun uri(name: String) = Uri.parse("content://autoexpand.test/$name")

    private fun settle() {
        val end = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        do {
            dispatcher.scheduler.runCurrent()
            if (vm.viewModelScope.coroutineContext[Job]!!.children.none { it.isActive }) return
            Thread.sleep(5)
        } while (System.nanoTime() < end)
        fail("asynchronous ViewModel operation did not complete; state=${vm.state.value}")
    }

    private fun select(cover: String = "small.png", withKey: Boolean = false) {
        vm.pick(DocSlot.INPUT, uri("payload.bin"))
        vm.pick(DocSlot.COVER, uri(cover))
        settle()
        if (withKey) {
            vm.useKey(true)
            vm.pick(DocSlot.KEY, uri("synthetic.stegkey"))
            settle()
        }
        assertNull(vm.state.value.error)
    }

    private fun capacity(): Preflight {
        vm.run(capacityOnly = true)
        settle()
        assertNull("capacity check failed: ${vm.state.value.error}", vm.state.value.error)
        val result = vm.state.value.result ?: throw AssertionError("capacity result was missing")
        assertNull("preflight must not stage an output", result.staged)
        return result.preflight ?: throw AssertionError("structured preflight was missing")
    }

    @Test fun defaultEnabledPreflightPlansEnoughCapacityForSmallCover() {
        assertTrue(vm.state.value.autoExpand)
        select()
        val plan = capacity()
        assertEquals(16, plan.originalWidth)
        assertEquals(16, plan.originalHeight)
        assertTrue(plan.expanded)
        assertTrue(plan.width > 16 && plan.height > 16)
        assertTrue(plan.fits)
        assertTrue(plan.ciphertextBytes <= plan.capacityBytes)
        assertEquals(expectedPayload.size, plan.originalBytes)
    }

    @Test fun disablingAutoExpandReportsOriginalInsufficientCapacity() {
        select()
        vm.autoExpand(false)
        assertFalse(vm.state.value.autoExpand)
        val plan = capacity()
        assertFalse(plan.expanded)
        assertFalse(plan.fits)
        assertEquals(16, plan.width)
        assertEquals(16, plan.height)
        assertEquals(StegEngine.capacity(16, 16), plan.capacityBytes)
    }

    @Test fun changingSettingInvalidatesPreviousCapacityResult() {
        select()
        assertTrue(capacity().fits)
        assertNotNull(vm.state.value.result)
        vm.autoExpand(false)
        assertNull("old expanded result must not represent the disabled setting", vm.state.value.result)
        assertNull(vm.state.value.error)
        assertFalse(capacity().fits)
        vm.autoExpand(true)
        assertNull(vm.state.value.result)
        assertTrue(capacity().fits)
    }

    @Test fun sufficientCoverKeepsItsOriginalDimensions() {
        select(cover = "large.png")
        val plan = capacity()
        assertTrue(plan.fits)
        assertFalse(plan.expanded)
        assertEquals(96, plan.originalWidth)
        assertEquals(96, plan.originalHeight)
        assertEquals(96, plan.width)
        assertEquals(96, plan.height)
    }

    @Test fun expandedHiddenPngRestoresOriginalNameAndBytes() {
        select(withKey = true)
        val planned = capacity()
        vm.run()
        settle()
        assertNull("hide failed: ${vm.state.value.error}", vm.state.value.error)
        val result = vm.state.value.result ?: throw AssertionError("hide result was missing")
        val staged = result.staged ?: throw AssertionError("validated PNG was not staged")
        assertTrue(staged.isFile)
        val output = staged.readBytes()
        assertEquals("image/png", result.mime)
        assertEquals(planned.width to planned.height, PngCodec.dimensions(output, Limits()))
        Credential.keyFile(originalFiles.getValue("synthetic.stegkey")).use { key ->
            val restored = StegEngine().decode(output, key)
            try {
                assertEquals("payload.bin", restored.filename)
                assertArrayEquals(expectedPayload, restored.data)
            } finally { restored.data.fill(0) }
        }
        assertEquals("the cover must never be used as the staged output", originalFiles.getValue("small.png").size.toLong(), File(directory, "small.png").length())
        vm.autoExpand(false)
        assertNull(vm.state.value.result)
        assertFalse("invalidating a result must clean its private staged output", staged.exists())
    }

    @Test fun busyTaskIgnoresAutoExpandChangesAndKeepsItsCapturedSetting() {
        select()
        vm.run(capacityOnly = true)
        assertTrue("run must enter busy state before launching work", vm.state.value.busy)
        vm.autoExpand(false)
        assertTrue(vm.state.value.autoExpand)
        settle()
        assertNull(vm.state.value.error)
        val plan = vm.state.value.result?.preflight ?: throw AssertionError("capacity result was missing")
        assertTrue(plan.expanded)
        assertTrue(plan.fits)
    }

    @Test fun disabledAutoExpandRejectsHideWithoutCreatingAnOutput() {
        select(withKey = true)
        vm.autoExpand(false)
        vm.run()
        settle()
        assertFalse(vm.state.value.busy)
        assertNull(vm.state.value.result)
        assertTrue("missing capacity refusal: ${vm.state.value.error}", vm.state.value.error.orEmpty().contains("容量不足"))
        val work = File(RuntimeEnvironment.getApplication().noBackupFilesDir, "moyle-work")
        assertTrue("failed hide left a staged file", work.listFiles().orEmpty().isEmpty())
    }

    class SyntheticDocuments(private val directory: File) : ContentProvider() {
        var writeRequests = 0
        var reportSize = true
        override fun onCreate() = true
        private fun file(uri: Uri): File {
            val name = uri.lastPathSegment ?: throw FileNotFoundException("missing synthetic name")
            val source = File(directory, name)
            if (source.parentFile?.canonicalFile != directory.canonicalFile || !source.isFile)
                throw FileNotFoundException("unknown synthetic input")
            return source
        }

        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            val source = file(uri)
            val columns = projection?.map { it }?.toTypedArray() ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
            return MatrixCursor(columns).apply {
                addRow(columns.map<String, Any?> { column ->
                    when (column) {
                        OpenableColumns.DISPLAY_NAME -> source.name
                        OpenableColumns.SIZE -> if(reportSize)source.length() else null
                        DocumentsContract.Document.COLUMN_LAST_MODIFIED -> source.lastModified()
                        else -> null
                    }
                }.toTypedArray())
            }
        }

        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            if (mode != "r") { writeRequests++; throw IllegalStateException("input must be read-only") }
            return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun getType(uri: Uri) = if (uri.lastPathSegment.orEmpty().endsWith(".png")) "image/png" else "application/octet-stream"
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    }
}
