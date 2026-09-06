package com.moyle.steg.android

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Exercises the real ViewModel with only the external document provider controlled. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class SelectionRegressionTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var vm: MoyleViewModel
    private val provider = DelayedDocuments()

    @Before fun setup() {
        Dispatchers.setMain(dispatcher)
        ShadowContentResolver.registerProviderInternal("selection.test", provider)
        vm = MoyleViewModel(RuntimeEnvironment.getApplication())
    }
    @After fun teardown() {
        provider.holds.values.forEach { it.release.countDown() }
        vm.viewModelScope.cancel()
        dispatcher.scheduler.runCurrent()
        Dispatchers.resetMain()
    }
    private fun uri(name: String) = Uri.parse("content://selection.test/$name")
    private fun awaitCondition(condition: () -> Boolean) {
        val end = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!condition() && System.nanoTime() < end) {
            dispatcher.scheduler.runCurrent()
            Thread.sleep(5)
        }
        dispatcher.scheduler.runCurrent()
        assertTrue("asynchronous operation did not complete", condition())
    }
    private fun settle() = awaitCondition {
        vm.viewModelScope.coroutineContext[Job]!!.children.none { it.isActive }
    }

    @Test fun pendingSelectionCannotStartTaskUsingPreviousInput() {
        vm.operation(Operation.ENCRYPT)
        vm.pick(DocSlot.INPUT, uri("A.txt")); settle()
        vm.setPassword("synthetic passphrase"); vm.setConfirmation("synthetic passphrase")
        val hold = provider.hold("B.txt")
        vm.pick(DocSlot.INPUT, uri("B.txt"))
        awaitCondition { hold.entered.count == 0L }
        vm.run()
        assertFalse("task started using A while selection B was unresolved", vm.state.value.busy)
        assertNull(vm.state.value.result)
        hold.release.countDown(); settle()
        assertEquals(uri("B.txt"), vm.state.value.input?.uri)
    }

    @Test fun olderSelectionCompletingLastCannotReplaceLatestInput() {
        val old = provider.hold("old.txt")
        vm.pick(DocSlot.INPUT, uri("old.txt"))
        awaitCondition { old.entered.count == 0L }
        vm.pick(DocSlot.INPUT, uri("new.txt"))
        awaitCondition { vm.state.value.input?.uri == uri("new.txt") }
        old.release.countDown(); settle()
        assertEquals(uri("new.txt"), vm.state.value.input?.uri)
        assertNull(vm.state.value.result)
    }

    @Test fun pageChangeInvalidatesPendingSelection() {
        val hold = provider.hold("old-page.txt")
        vm.pick(DocSlot.INPUT, uri("old-page.txt"))
        awaitCondition { hold.entered.count == 0L }
        vm.page(1)
        hold.release.countDown(); settle()
        assertNull(vm.state.value.input)
        assertNull(vm.state.value.error)
    }

    @Test fun staleFailureCannotOverwriteNewSelectionStatus() {
        val hold = provider.hold("old-error.txt", fail = true)
        vm.pick(DocSlot.INPUT, uri("old-error.txt"))
        awaitCondition { hold.entered.count == 0L }
        vm.pick(DocSlot.INPUT, uri("new.txt"))
        awaitCondition { vm.state.value.input?.uri == uri("new.txt") }
        hold.release.countDown(); settle()
        assertEquals(uri("new.txt"), vm.state.value.input?.uri)
        assertNull(vm.state.value.error)
    }

    @Test fun independentSlotsMayCompleteInEitherOrder() {
        val cover = provider.hold("cover.png")
        vm.pick(DocSlot.COVER, uri("cover.png"))
        awaitCondition { cover.entered.count == 0L }
        vm.pick(DocSlot.INPUT, uri("payload.txt"))
        awaitCondition { vm.state.value.input?.uri == uri("payload.txt") }
        cover.release.countDown(); settle()
        assertEquals(uri("cover.png"), vm.state.value.cover?.uri)
        assertEquals(uri("payload.txt"), vm.state.value.input?.uri)
    }

    @Test fun explicitCancelDropsLateSelectionAndReleasesTaskGate() {
        val hold = provider.hold("cancelled.txt")
        vm.pick(DocSlot.INPUT, uri("cancelled.txt"))
        awaitCondition { hold.entered.count == 0L }
        assertTrue(vm.state.value.selecting)
        vm.cancelSelection()
        assertFalse(vm.state.value.selecting)
        hold.release.countDown(); settle()
        assertNull(vm.state.value.input)
        assertNull(vm.state.value.error)
    }

    @Test fun operationChangeDropsPendingSelection() {
        val hold = provider.hold("old-operation.txt")
        vm.pick(DocSlot.INPUT, uri("old-operation.txt"))
        awaitCondition { hold.entered.count == 0L }
        vm.operation(Operation.KEYGEN)
        hold.release.countDown(); settle()
        assertFalse(vm.state.value.selecting)
        assertNull(vm.state.value.input)
    }

    @Test fun failedNewSelectionCannotFallBackToPreviousFile() {
        vm.pick(DocSlot.INPUT, uri("A.txt")); settle()
        val hold = provider.hold("failed.txt", fail = true)
        vm.pick(DocSlot.INPUT, uri("failed.txt"))
        awaitCondition { hold.entered.count == 0L }
        hold.release.countDown(); settle()
        assertFalse(vm.state.value.selecting)
        assertNull(vm.state.value.input)
        assertNotNull(vm.state.value.error)
    }

    @Test fun credentialModeChangeDropsLateKeySelection() {
        vm.useKey(true)
        val hold = provider.hold("old.stegkey")
        vm.pick(DocSlot.KEY, uri("old.stegkey"))
        awaitCondition { hold.entered.count == 0L }
        vm.useKey(false)
        hold.release.countDown(); settle()
        assertFalse(vm.state.value.selecting)
        assertFalse(vm.state.value.useKey)
        assertNull(vm.state.value.key)
    }

    class Hold(val fail: Boolean) {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
    }
    class DelayedDocuments : ContentProvider() {
        val holds = ConcurrentHashMap<String, Hold>()
        fun hold(name: String, fail: Boolean = false) = Hold(fail).also { holds[name] = it }
        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            holds[uri.lastPathSegment]?.let {
                it.entered.countDown()
                check(it.release.await(10, TimeUnit.SECONDS)) { "test provider timed out" }
                if (it.fail) throw IllegalStateException("synthetic provider failure")
            }
            return MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME)).apply { addRow(arrayOf(uri.lastPathSegment)) }
        }
        override fun getType(uri: Uri) = "application/octet-stream"
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    }
}
