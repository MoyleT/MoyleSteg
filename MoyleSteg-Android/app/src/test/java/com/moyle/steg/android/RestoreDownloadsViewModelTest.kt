package com.moyle.steg.android

import android.content.pm.ProviderInfo
import android.net.Uri
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.concurrent.TimeUnit

/** End-to-end recovery should finish with a saved, openable download, not a location picker. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RestoreDownloadsViewModelTest {
    private val dispatcher=StandardTestDispatcher()
    private lateinit var vm:MoyleViewModel
    private lateinit var directory:File
    private lateinit var sourceProvider:AutoExpandViewModelTest.SyntheticDocuments
    private lateinit var downloadProvider:DownloadsExporterTest.DownloadsProvider
    private lateinit var downloadDirectory:File
    private var permissionDenied=false
    private val plaintext="%PDF-1.7\nSynthetic recovery file; no personal content.\n%%EOF\n".toByteArray()
    private val key=Credential.exportKey(ByteArray(32){it.toByte()})

    @Before fun setup(){
        Dispatchers.setMain(dispatcher)
        val app=RuntimeEnvironment.getApplication()
        directory=File.createTempFile("restore-download-",".test",app.cacheDir)
        check(directory.delete() && directory.mkdir())
        sourceProvider=AutoExpandViewModelTest.SyntheticDocuments(directory)
        sourceProvider.attachInfo(app,ProviderInfo().apply{
            authority="restore-download.test";packageName=app.packageName;name=sourceProvider.javaClass.name
            applicationInfo=app.applicationInfo;exported=true;grantUriPermissions=true
        })
        ShadowContentResolver.registerProviderInternal("restore-download.test",sourceProvider)
        downloadDirectory=File(directory,"downloads").apply{check(mkdir())}
        downloadProvider=DownloadsExporterTest.DownloadsProvider(downloadDirectory)
        downloadProvider.attachInfo(app,ProviderInfo().apply{
            authority="media";packageName=app.packageName;name=downloadProvider.javaClass.name
            applicationInfo=app.applicationInfo;exported=true;grantUriPermissions=true
        })
        ShadowContentResolver.registerProviderInternal("media",downloadProvider)
        File(directory,"synthetic.stegkey").writeBytes(key)
        Credential.keyFile(key).use{credential->
            File(directory,"example.saes").writeBytes(StegEngine().encrypt("example.pdf",plaintext,credential))
            val rgba=RgbaImage(96,64,ByteArray(96*64*4){if(it%4==3)255.toByte() else (it*13).toByte()})
            File(directory,"example.png").writeBytes(StegEngine().hide(PngCodec.encode(rgba),"example.pdf",plaintext,credential))
            val gif=javaClass.classLoader!!.getResourceAsStream("gif/cover.gif")!!.use{it.readBytes()}
            File(directory,"example.gif").writeBytes(StegEngine().hide(gif,"example.pdf",plaintext,credential))
        }
        val realWriter=DownloadsExporter(app)
        vm=MoyleViewModel(app,downloads=DownloadWriter{file,name,mime,hash,ctl->
            if(permissionDenied)throw DownloadPermissionException()
            realWriter.save(file,name,mime,hash,ctl)
        })
    }
    @After fun cleanup(){
        vm.viewModelScope.cancel();dispatcher.scheduler.runCurrent();vm.clearResult()
        assertEquals(0,sourceProvider.writeRequests)
        check(downloadDirectory.deleteRecursively())
        directory.listFiles().orEmpty().forEach{check(it.delete())};check(directory.delete())
        Dispatchers.resetMain()
    }
    private fun uri(name:String)=Uri.parse("content://restore-download.test/$name")
    private fun settle(){
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(30)
        do{
            dispatcher.scheduler.runCurrent()
            if(vm.viewModelScope.coroutineContext[Job]!!.children.none{it.isActive})return
            Thread.sleep(5)
        }while(System.nanoTime()<deadline)
        fail("Recovery did not finish: ${vm.state.value.stage}")
    }
    private fun prepare(name:String){
        vm.operation(Operation.RESTORE);vm.pick(DocSlot.INPUT,uri(name));settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("synthetic.stegkey"));settle()
    }
    private fun restore(name:String):JobResult{
        prepare(name);vm.run();settle()
        assertNull(vm.state.value.error)
        return vm.state.value.result ?: throw AssertionError("missing result")
    }
    @Test fun authenticatedSaesAutomaticallySavesBeforeReportingCompletion(){
        val result=restore("example.saes")
        assertNotNull("Restoring must save to Download without requiring a file picker",result.exportedUri)
        assertEquals("application/pdf",result.mime)
        assertArrayEquals(plaintext,downloadProvider.rows.getValue(result.exportedUri!!).file.readBytes())
        assertEquals("Download/example.pdf",result.download!!.displayPath)
    }
    @Test fun authenticatedPngUsesTheSameAutomaticDownloadFlow(){
        val result=restore("example.png")
        assertNotNull("Restoring must save to Download without requiring a file picker",result.exportedUri)
        assertEquals("application/pdf",result.mime)
    }
    @Test fun authenticatedGifAlsoSavesTheRestoredFile(){
        val result=restore("example.gif")
        assertArrayEquals(plaintext,downloadProvider.rows.getValue(result.exportedUri!!).file.readBytes())
    }
    @Test fun saveFailureCanRetryWithoutReadingTheContainerOrKeyAgain(){
        downloadProvider.refuseWrite=true
        prepare("example.saes");vm.run();settle()
        val pending=vm.state.value.result!!
        assertTrue(pending.restored);assertNull(pending.exportedUri)
        assertNotNull(vm.state.value.error)
        assertArrayEquals(plaintext,pending.staged!!.readBytes())
        assertTrue(downloadProvider.rows.isEmpty())
        File(directory,"example.saes").writeText("now invalid input")
        File(directory,"synthetic.stegkey").writeText("now invalid key")
        downloadProvider.refuseWrite=false
        vm.saveRestoredToDownloads();settle()
        val saved=vm.state.value.result!!
        assertNull(vm.state.value.error)
        assertArrayEquals(plaintext,downloadProvider.rows.getValue(saved.exportedUri!!).file.readBytes())
        vm.saveRestoredToDownloads();settle()
        assertEquals("retry after success must not create a duplicate",1,downloadProvider.rows.size)
    }
    @Test fun clearResultRemovesOnlyPrivateCopyAndLeavesDownload(){
        val r=restore("example.png")
        val publicFile=downloadProvider.rows.getValue(r.exportedUri!!).file
        vm.clearResult()
        assertNull(vm.state.value.result)
        assertFalse(r.staged!!.exists())
        assertArrayEquals(plaintext,publicFile.readBytes())
    }
    @Test fun clearingResultMakesOldPermissionCallbackInert(){
        permissionDenied=true
        prepare("example.saes");vm.run();settle()
        val token=vm.state.value.downloadPermissionRequest!!
        val staged=vm.state.value.result!!.staged!!
        vm.consumeDownloadPermissionRequest(token)
        assertNull(vm.state.value.downloadPermissionRequest)
        vm.clearResult();permissionDenied=false
        vm.onDownloadPermissionResult(token,true);settle()
        assertNull(vm.state.value.result);assertFalse(staged.exists())
        assertTrue(downloadProvider.rows.isEmpty())
    }
    @Test fun permissionDenialAndLaterGrantKeepTheAuthenticatedResult(){
        permissionDenied=true
        prepare("example.png");vm.run();settle()
        val token=vm.state.value.downloadPermissionRequest!!
        vm.consumeDownloadPermissionRequest(token);vm.onDownloadPermissionResult(token,false)
        assertTrue(vm.state.value.result!!.staged!!.exists())
        assertTrue(vm.state.value.error!!.contains("未获得"))
        vm.saveRestoredToDownloads();settle()
        val retryToken=vm.state.value.downloadPermissionRequest!!
        assertNotEquals(token,retryToken)
        permissionDenied=false
        vm.onDownloadPermissionResult(token,true);settle()
        assertTrue(downloadProvider.rows.isEmpty())
        vm.consumeDownloadPermissionRequest(retryToken);vm.onDownloadPermissionResult(retryToken,true);settle()
        assertNotNull(vm.state.value.result!!.exportedUri)
        assertNull(vm.state.value.downloadPermissionRequest)
    }
    @Test fun cancelWhileReadingBackPreservesStagingForRetry(){
        downloadProvider.beforeRead={vm.requestCancel()}
        prepare("example.png");vm.run();settle()
        assertNull(vm.state.value.result!!.exportedUri)
        assertTrue(vm.state.value.result!!.staged!!.exists())
        assertTrue(downloadProvider.rows.isEmpty())
        downloadProvider.beforeRead={}
        vm.saveRestoredToDownloads();settle()
        assertNotNull(vm.state.value.result!!.exportedUri)
        assertNull(vm.state.value.error)
    }
    @Test fun cancellationAfterCommitStillReportsSavedFile(){
        downloadProvider.afterPublish={vm.requestCancel()}
        val r=restore("example.png")
        assertNotNull(r.exportedUri);assertEquals("完成",vm.state.value.stage)
    }
    @Test fun verificationNeverPublishesAPlaintextDownload(){
        prepare("example.saes");vm.operation(Operation.VERIFY);vm.run();settle()
        assertNull(vm.state.value.error);assertNull(vm.state.value.result!!.staged)
        assertNull(vm.state.value.result!!.exportedUri)
        assertTrue(downloadProvider.rows.isEmpty())
    }
    @Test fun wrongCredentialNeverPublishes(){
        prepare("example.saes")
        File(directory,"synthetic.stegkey").writeBytes(Credential.exportKey(ByteArray(32){7}))
        vm.run();settle()
        assertNotNull(vm.state.value.error);assertNull(vm.state.value.result)
        assertTrue(downloadProvider.rows.isEmpty())
    }
}
