package com.moyle.steg.android

import android.content.pm.ProviderInfo
import android.net.Uri
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
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
import java.util.Random
import java.util.concurrent.TimeUnit

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class GifViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var vm: MoyleViewModel
    private lateinit var directory: File
    private lateinit var provider: AutoExpandViewModelTest.SyntheticDocuments
    private val source = ByteArray(1024).also { Random(718L).nextBytes(it) }
    private val keyFile = Credential.exportKey(ByteArray(32) { it.toByte() })
    private lateinit var cover: ByteArray

    @Before fun setup() {
        Dispatchers.setMain(dispatcher)
        val app = RuntimeEnvironment.getApplication()
        directory = File.createTempFile("gif-vm-", ".test", app.cacheDir)
        check(directory.delete() && directory.mkdir())
        provider = AutoExpandViewModelTest.SyntheticDocuments(directory)
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "gif.test"; packageName = app.packageName
            name = provider.javaClass.name; applicationInfo = app.applicationInfo
            exported = true; grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("gif.test", provider)
        cover = javaClass.classLoader!!.getResourceAsStream("gif/cover.gif")!!.use { it.readBytes() }
        File(directory, "cover.gif").writeBytes(cover)
        File(directory, "synthetic.bin").writeBytes(source)
        File(directory, "test.stegkey").writeBytes(keyFile)
        vm = MoyleViewModel(app)
    }

    @After fun teardown() {
        try {
            vm.viewModelScope.cancel(); dispatcher.scheduler.runCurrent(); vm.clearResult()
            assertEquals(0, provider.writeRequests)
            assertArrayEquals(cover, File(directory, "cover.gif").readBytes())
            assertArrayEquals(source, File(directory, "synthetic.bin").readBytes())
            assertArrayEquals(keyFile, File(directory, "test.stegkey").readBytes())
        } finally {
            Dispatchers.resetMain()
            directory.listFiles()?.forEach { check(it.delete()) }; check(directory.delete())
        }
    }

    private fun uri(name: String) = Uri.parse("content://gif.test/$name")
    private fun settle() {
        val end = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
        do {
            dispatcher.scheduler.runCurrent()
            if (vm.viewModelScope.coroutineContext[Job]!!.children.none { it.isActive }) return
            Thread.sleep(5)
        } while (System.nanoTime() < end)
        fail("ViewModel task did not complete")
    }
    private fun prepare() {
        vm.pick(DocSlot.COVER, uri("cover.gif"))
        vm.pick(DocSlot.INPUT, uri("synthetic.bin")); settle()
        vm.useKey(true); vm.pick(DocSlot.KEY, uri("test.stegkey")); settle()
        assertNull(vm.state.value.error)
    }
    private fun hide(): JobResult {
        prepare(); vm.run(); settle()
        assertNull(vm.state.value.error)
        return vm.state.value.result ?: throw AssertionError("no GIF result")
    }

    @Test fun preflightReportsAnimationAndExactSavedSizeWithoutResizing() {
        prepare(); vm.run(capacityOnly = true); settle()
        assertNull(vm.state.value.error)
        val plan = vm.state.value.result!!.preflight!!
        assertEquals("gif", plan.format); assertEquals(3, plan.frameCount)
        assertEquals(8, plan.width); assertEquals(6, plan.height)
        assertFalse(plan.expanded); assertTrue(plan.fits)
        assertNull(vm.state.value.result!!.staged)
        vm.run(); settle(); assertNull(vm.state.value.error)
        assertEquals(plan.outputBytes, vm.state.value.result!!.staged!!.length())
    }

    @Test fun gifUsesMatchingMimeAndFilenameAndPassesSavedAuthentication() {
        val result = hide()
        assertEquals("image/gif", result.mime)
        assertEquals("moyle_hidden.gif", result.suggestedName)
        val bytes = result.staged!!.readBytes()
        assertTrue(GifCarrier.isGif(bytes))
        assertEquals(sha256(bytes), result.containerHash)
        Credential.keyFile(keyFile).use { key ->
            val decoded = StegEngine().decode(bytes, key)
            assertEquals("synthetic.bin", decoded.filename); assertArrayEquals(source, decoded.data)
        }
    }

    @Test fun gifReadOnlyVerificationBindsBothDigestsAndDoesNotStagePlaintext() {
        val bytes = hide().staged!!.readBytes()
        File(directory, "hidden.gif").writeBytes(bytes)
        vm.page(1); vm.operation(Operation.VERIFY)
        vm.pick(DocSlot.INPUT, uri("hidden.gif")); settle()
        vm.run(); settle(); assertNull(vm.state.value.error)
        val result = vm.state.value.result!!
        assertNull(result.staged); assertEquals(sha256(source), result.contentHash)
        assertEquals(sha256(bytes), result.containerHash)
    }

    @Test fun gifRestoreKeepsOriginalFilenameAndBytesWithAutoExpandStillEnabled() {
        val bytes = hide().staged!!.readBytes()
        File(directory, "hidden.gif").writeBytes(bytes)
        vm.page(1); vm.pick(DocSlot.INPUT, uri("hidden.gif")); settle()
        assertTrue(vm.state.value.autoExpand)
        vm.run(); settle(); assertNull(vm.state.value.error)
        val result = vm.state.value.result!!
        assertEquals("synthetic.bin", result.suggestedName)
        assertArrayEquals(source, result.staged!!.readBytes())
        assertArrayEquals(bytes, File(directory, "hidden.gif").readBytes())
    }
}
