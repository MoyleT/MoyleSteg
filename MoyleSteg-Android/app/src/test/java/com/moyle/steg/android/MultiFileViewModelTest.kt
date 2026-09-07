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
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Whole-container authentication must precede member selection and public writes. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class MultiFileViewModelTest {
    private val dispatcher=StandardTestDispatcher()
    private lateinit var vm:MoyleViewModel
    private lateinit var directory:File
    private lateinit var inputs:AutoExpandViewModelTest.SyntheticDocuments
    private lateinit var publicFiles:DownloadsExporterTest.DownloadsProvider
    private var failSave=0
    private var saveCalls=0
    private var permissionDenied=false
    private var privateSpace:(File)->Long={it.usableSpace}
    private val key=Credential.exportKey(ByteArray(32){it.toByte()})
    private val names=listOf("report.txt","report.txt","报告.pdf")
    private val bytes=listOf("first synthetic file".toByteArray(),byteArrayOf(),"%PDF-1.7\nSynthetic PDF\n%%EOF\n".toByteArray())

    @Before fun setup(){
        Dispatchers.setMain(dispatcher)
        val app=RuntimeEnvironment.getApplication()
        directory=File.createTempFile("bundle-vm-",".test",app.cacheDir)
        check(directory.delete() && directory.mkdir())
        inputs=AutoExpandViewModelTest.SyntheticDocuments(directory)
        inputs.attachInfo(app,ProviderInfo().apply{
            authority="bundle-vm.test";packageName=app.packageName;name=inputs.javaClass.name
            applicationInfo=app.applicationInfo;exported=true;grantUriPermissions=true
        })
        ShadowContentResolver.registerProviderInternal("bundle-vm.test",inputs)
        publicFiles=DownloadsExporterTest.DownloadsProvider(File(directory,"public").apply{check(mkdir())})
        publicFiles.attachInfo(app,ProviderInfo().apply{
            authority="media";packageName=app.packageName;name=publicFiles.javaClass.name
            applicationInfo=app.applicationInfo;exported=true;grantUriPermissions=true
        })
        ShadowContentResolver.registerProviderInternal("media",publicFiles)
        File(directory,"test.stegkey").writeBytes(key)
        val writer=DownloadsExporter(app)
        vm=MoyleViewModel(app,downloads=DownloadWriter{file,name,mime,hash,ctl->
            if(permissionDenied)throw DownloadPermissionException()
            saveCalls++
            if(saveCalls==failSave)throw java.io.IOException("synthetic full disk")
            writer.save(file,name,mime,hash,ctl)
        },privateSpace={privateSpace(it)})
    }
    @After fun cleanup(){
        vm.viewModelScope.cancel();dispatcher.scheduler.runCurrent();vm.clearResult()
        assertEquals(0,inputs.writeRequests)
        assertTrue(directory.deleteRecursively())
        Dispatchers.resetMain()
    }
    private fun uri(name:String)=Uri.parse("content://bundle-vm.test/$name")
    private fun settle(){
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(40)
        do{dispatcher.scheduler.runCurrent();if(vm.viewModelScope.coroutineContext[Job]!!.children.none{it.isActive})return;Thread.sleep(5)}while(System.nanoTime()<deadline)
        fail("Unfinished task: ${vm.state.value.stage}")
    }
    private fun archive(marked:Boolean=true):File{
        val file=File(directory,if(marked)"managed.zip" else "ordinary.zip")
        ZipOutputStream(file.outputStream(),Charsets.UTF_8).use{out->
            if(marked)out.setComment("MOYLESTEG-BUNDLE-V1")
            for(i in names.indices){
                out.putNextEntry(ZipEntry("%04d/%s".format(i+1,names[i])).apply{time=315532800000L})
                out.write(bytes[i]);out.closeEntry()
            }
        }
        return file
    }
    private fun restoreZip(marked:Boolean=true,format:String="saes"):JobResult{
        val zip=archive(marked)
        Credential.keyFile(key).use{credential->
            val payload=zip.readBytes()
            val output=when(format){
                "png"->{val rgba=RgbaImage(96,96,ByteArray(96*96*4){if(it%4==3)255.toByte()else(it*13).toByte()})
                    StegEngine().hide(PngCodec.encode(rgba),zip.name,payload,credential)}
                "gif"->{val cover=javaClass.classLoader!!.getResourceAsStream("gif/cover.gif")!!.use{it.readBytes()}
                    StegEngine().hide(cover,zip.name,payload,credential)}
                else->StegEngine().encrypt(zip.name,payload,credential)
            }
            File(directory,"container.$format").writeBytes(output)
        }
        vm.operation(Operation.RESTORE);vm.pick(DocSlot.INPUT,uri("container.$format"));settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        vm.run();settle()
        assertNull(vm.state.value.error)
        return vm.state.value.result ?: throw AssertionError("no recovery result")
    }
    @Test fun managedBundleWaitsForMemberSelectionBeforePublishingAnyFiles(){
        val r=restoreZip()
        assertNotNull(r.staged)
        assertTrue("Managed bundles must let the user choose members before any public write",publicFiles.rows.isEmpty())
        assertNull(r.exportedUri)
        assertEquals(names,r.members.map{it.entry.name})
        assertEquals(bytes.map{sha256(it)},r.members.map{it.entry.sha256})
    }

    @Test fun settingsPreservesPartialRecoveryAndRetryNeedsNoSourceOrKey(){
        val initial=restoreZip()
        vm.selectAllRestoredMembers(false);vm.selectRestoredMember(1,true)
        vm.saveBundleSelection();settle()
        val partial=requireNotNull(vm.state.value.result)
        val saved=partial.members.single{it.saved!=null}.saved!!
        File(directory,"container.saes").writeText("source is unavailable now")
        File(directory,"test.stegkey").writeText("key is unavailable now")
        vm.page(3);vm.theme("blossom");vm.largeText(true);vm.page(1)
        assertSame(partial,vm.state.value.result)
        assertTrue(initial.staged!!.isFile)
        vm.selectAllRestoredMembers(true);vm.saveBundleSelection();settle()
        assertEquals(3,vm.state.value.result!!.members.count{it.saved!=null})
        assertEquals(saved,vm.state.value.result!!.members.first{it.entry.index==1}.saved)
        assertEquals(3,saveCalls)
    }

    @Test fun multiFileWorkspaceIsRejectedBeforeCapturingInputs(){
        vm.operation(Operation.ENCRYPT)
        val sourceUris=(1..2).map{index->
            val content=ByteArray(32768).also{java.util.Random(index.toLong()).nextBytes(it)}
            File(directory,"large-$index.bin").writeBytes(content);uri("large-$index.bin")
        }
        vm.pickInputs(sourceUris);settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        privateSpace={32L*1024*1024+100*1024-it.listFiles().orEmpty().sumOf{f->f.length()}}
        inputs.readRequests=0
        vm.run();settle()
        assertTrue(vm.state.value.error.orEmpty().contains("空间"))
        assertNull(vm.state.value.result)
        assertEquals("Rejected workspace must not capture provider files",0,inputs.readRequests)
        assertTrue(DocumentStore(RuntimeEnvironment.getApplication()).workDirectory().listFiles().orEmpty().isEmpty())
    }

    @Test fun memberDiskBudgetFailureKeepsAuthenticatedArchiveForRetry(){
        val r=restoreZip()
        privateSpace={32L*1024*1024}
        vm.saveBundleSelection();settle()
        assertTrue(vm.state.value.error.orEmpty().contains("空间"))
        assertEquals(0,saveCalls)
        assertTrue(r.staged!!.isFile)
        privateSpace={it.usableSpace}
        vm.saveBundleSelection();settle()
        assertEquals(3,saveCalls)
        assertTrue(vm.state.value.result!!.members.all{it.saved!=null})
    }
    @Test fun verifiedBundleReleasesOriginalCapturesBeforeEncryptionWorkspace(){
        vm.operation(Operation.ENCRYPT)
        val uris=(1..2).map{index->File(directory,"part-$index.txt").writeText("synthetic $index");uri("part-$index.txt")}
        vm.pickInputs(uris);settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        val retainedCounts=mutableListOf<Int>()
        privateSpace={dir->
            if(vm.state.value.stage=="检查加密暂存空间")retainedCounts+=dir.listFiles().orEmpty().size
            dir.usableSpace
        }
        vm.run();settle()
        assertNull(vm.state.value.error)
        assertTrue(retainedCounts.isNotEmpty())
        assertEquals("Only the authenticated ZIP should remain before encryption allocates its workspace",1,retainedCounts.first())
        assertTrue(vm.state.value.result!!.staged!!.isFile)
    }

    @Test fun confirmedDiscardOfPartiallySavedBundlePreservesPublicFile(){
        val initial=restoreZip()
        vm.selectAllRestoredMembers(false);vm.selectRestoredMember(1,true)
        vm.saveBundleSelection();settle()
        val savedBytes=publicFiles.rows.values.map{it.file.readBytes()}
        vm.page(0)
        assertTrue(initial.staged!!.exists())
        assertNotNull(vm.state.value.discardRequest)
        vm.keepCurrentWork()
        assertTrue(initial.staged.isFile)
        vm.page(0);vm.confirmDiscard()
        assertFalse(initial.staged.exists())
        assertEquals(1,publicFiles.rows.size)
        assertArrayEquals(savedBytes.single(),publicFiles.rows.values.single().file.readBytes())
    }
    @Test fun ordinaryUserZipRemainsOneFileAndSavesAutomatically(){
        val r=restoreZip(marked=false)
        assertNotNull(r.exportedUri)
        assertEquals("application/zip",r.mime)
        assertEquals(1,publicFiles.rows.size)
        assertArrayEquals(File(directory,"ordinary.zip").readBytes(),publicFiles.rows.getValue(r.exportedUri!!).file.readBytes())
    }
    @Test fun chooseOneThenRemainingPreservesBytesAndNeverRepeatsCommittedItems(){
        restoreZip()
        vm.selectAllRestoredMembers(false);vm.selectRestoredMember(3,true)
        vm.saveBundleSelection();settle()
        var r=vm.state.value.result!!
        assertEquals(1,publicFiles.rows.size)
        assertEquals("application/pdf",r.members[2].saved!!.mime)
        assertArrayEquals(bytes[2],publicFiles.rows.getValue(r.members[2].saved!!.uri).file.readBytes())
        vm.selectAllRestoredMembers(true);vm.saveBundleSelection();settle()
        r=vm.state.value.result!!
        assertEquals(3,publicFiles.rows.size);assertEquals(3,saveCalls)
        r.members.forEachIndexed{i,m->assertArrayEquals(bytes[i],publicFiles.rows.getValue(m.saved!!.uri).file.readBytes())}
        assertNotEquals(r.members[0].saved!!.displayName,r.members[1].saved!!.displayName)
        vm.saveBundleSelection();settle();assertEquals(3,saveCalls)
    }
    @Test fun saveFailureRetainsPriorCommitsAndRetriesWithoutOriginalContainerOrCredential(){
        restoreZip();failSave=2
        vm.saveBundleSelection();settle()
        assertNotNull(vm.state.value.error)
        assertEquals(1,publicFiles.rows.size)
        assertNotNull(vm.state.value.result!!.members[0].saved)
        File(directory,"container.saes").writeText("replaced after authenticated capture")
        File(directory,"test.stegkey").writeText("replaced after authenticated capture")
        vm.saveBundleSelection();settle()
        assertNull(vm.state.value.error);assertEquals(3,publicFiles.rows.size)
        assertEquals(4,saveCalls)
        assertTrue(vm.state.value.result!!.members.all{it.saved!=null && it.error==null})
    }
    @Test fun cancelAfterOneCommitKeepsItAndAllowsRemainingRetry(){
        restoreZip();publicFiles.afterPublish={vm.requestCancel()}
        vm.saveBundleSelection();settle()
        assertEquals(1,publicFiles.rows.size)
        assertEquals(1,vm.state.value.result!!.members.count{it.saved!=null})
        assertNotNull(vm.state.value.error)
        publicFiles.afterPublish={}
        vm.saveBundleSelection();settle()
        assertEquals(3,publicFiles.rows.size);assertNull(vm.state.value.error)
    }
    @Test fun cancelAfterFinalCommitReportsSuccessfulSave(){
        restoreZip();vm.selectAllRestoredMembers(false);vm.selectRestoredMember(3,true)
        publicFiles.afterPublish={vm.requestCancel()}
        vm.saveBundleSelection();settle()
        assertEquals(1,publicFiles.rows.size);assertNull(vm.state.value.error)
    }
    @Test fun clearingResultCleansPrivateArchiveButKeepsPublicMembers(){
        val staged=restoreZip().staged!!
        vm.saveBundleSelection();settle()
        vm.clearResult()
        assertFalse(staged.exists());assertNull(vm.state.value.result)
        assertTrue(publicFiles.rows.values.all{it.file.exists()})
    }
    @Test fun permissionResponseCannotSaveChangedSelection(){
        restoreZip();permissionDenied=true;vm.saveBundleSelection();settle()
        val token=vm.state.value.downloadPermissionRequest!!
        vm.selectAllRestoredMembers(false);vm.selectRestoredMember(3,true)
        permissionDenied=false;vm.onDownloadPermissionResult(token,true);settle()
        assertTrue(publicFiles.rows.isEmpty())
        vm.saveBundleSelection();settle();assertEquals(1,publicFiles.rows.size)
    }
    @Test fun permissionGrantRetriesTheSameUnchangedSelection(){
        restoreZip();vm.selectAllRestoredMembers(false);vm.selectRestoredMember(3,true)
        permissionDenied=true;vm.saveBundleSelection();settle()
        val token=vm.state.value.downloadPermissionRequest!!
        permissionDenied=false;vm.onDownloadPermissionResult(token,true);settle()
        assertEquals(1,publicFiles.rows.size);assertNotNull(vm.state.value.result!!.members[2].saved)
    }
    @Test fun tamperedPrivateArchiveIsRejectedBeforePublicWrite(){
        val staged=restoreZip().staged!!
        java.io.RandomAccessFile(staged,"rw").use{it.seek(35);it.write(127)}
        vm.saveBundleSelection();settle()
        assertNotNull(vm.state.value.error);assertTrue(publicFiles.rows.isEmpty())
    }
    @Test fun createMultipleFilesProducesCompatibleWholeZipAndSelectionCanRemoveItems(){
        File(directory,"one.txt").writeBytes(bytes[0]);File(directory,"two.pdf").writeBytes(bytes[2])
        vm.operation(Operation.ENCRYPT)
        vm.pickInputs(listOf(uri("one.txt"),uri("two.pdf"),uri("one.txt")));settle()
        assertEquals(2,vm.state.value.inputs.size)
        vm.removeInput(uri("two.pdf"));assertEquals(1,vm.state.value.inputs.size)
        vm.pickInputs(listOf(uri("two.pdf")));settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        vm.run();settle();assertNull(vm.state.value.error)
        val r=vm.state.value.result!!
        assertTrue(r.inputLabel.contains("2"))
        Credential.keyFile(key).use{c->
            // Existing v1 decoder needs no awareness of bundle format.
            val decoded=StegEngine().decode(r.staged!!.readBytes(),c)
            assertEquals("MoyleSteg-files.zip",decoded.filename)
            val zip=File(directory,"recovered.zip").apply{writeBytes(decoded.data)}
            val info=MultiFileBundle.inspect(zip,1024*1024,1024*1024)!!
            assertEquals(listOf("one.txt","two.pdf"),info.entries.map{it.name})
            assertEquals(listOf(sha256(bytes[0]),sha256(bytes[2])),info.entries.map{it.sha256})
        }
        assertTrue(publicFiles.rows.isEmpty())
    }
    @Test fun imagePreflightUsesActualBundleAndFinalPngRestoresBothFiles(){
        File(directory,"one.txt").writeBytes(bytes[0]);File(directory,"two.pdf").writeBytes(bytes[2])
        val rgba=RgbaImage(96,64,ByteArray(96*64*4){if(it%4==3)255.toByte()else (it*13).toByte()})
        File(directory,"cover.png").writeBytes(PngCodec.encode(rgba))
        vm.pickInputs(listOf(uri("one.txt"),uri("two.pdf")));vm.pick(DocSlot.COVER,uri("cover.png"));settle()
        vm.run(capacityOnly=true);settle();assertNull(vm.state.value.error)
        val required=vm.state.value.result!!.preflight!!.originalBytes
        assertTrue(required>bytes[0].size+bytes[2].size)
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        vm.run();settle();assertNull(vm.state.value.error)
        val r=vm.state.value.result!!
        Credential.keyFile(key).use{c->
            val decoded=StegEngine().decode(r.staged!!.readBytes(),c)
            assertEquals(required,decoded.data.size)
            val zip=File(directory,"recovered.zip").apply{writeBytes(decoded.data)}
            assertEquals(2,MultiFileBundle.inspect(zip,1024*1024,1024*1024)!!.entries.size)
        }
    }
    @Test fun excessiveSelectionRejectedBeforeOpeningAnyNewFiles(){
        vm.pickInputs((1..101).map{uri("$it.txt")});settle()
        assertNotNull(vm.state.value.error);assertNull(vm.state.value.input)
    }
    @Test fun delayedSavePickerCannotExportAReplacementResult(){
        restoreZip();val token=vm.requestExport()!!
        vm.clearResult();restoreZip()
        vm.completeExport(token,uri("stale-output.zip"));settle()
        assertEquals(0,inputs.writeRequests)
        assertFalse(File(directory,"stale-output.zip").exists())
        assertNull(vm.state.value.result!!.exportedUri)
    }
    @Test fun pngBundleUsesTheSameAuthenticatedSelectionFlow(){
        val r=restoreZip(format="png");assertEquals(3,r.members.size);assertTrue(publicFiles.rows.isEmpty())
        vm.saveBundleSelection();settle();assertNull(vm.state.value.error)
        vm.state.value.result!!.members.forEachIndexed{i,m->assertArrayEquals(bytes[i],publicFiles.rows.getValue(m.saved!!.uri).file.readBytes())}
    }
    @Test fun gifBundleUsesTheSameAuthenticatedSelectionFlow(){
        val r=restoreZip(format="gif");assertEquals(3,r.members.size);assertTrue(publicFiles.rows.isEmpty())
        vm.saveBundleSelection();settle();assertNull(vm.state.value.error)
        vm.state.value.result!!.members.forEachIndexed{i,m->assertArrayEquals(bytes[i],publicFiles.rows.getValue(m.saved!!.uri).file.readBytes())}
    }
    @Test fun singleMultiPickerSelectionKeepsOriginalNameAndDoesNotWrapZip(){
        File(directory,"one.txt").writeBytes(bytes[0])
        vm.operation(Operation.ENCRYPT);vm.pickInputs(listOf(uri("one.txt")));settle()
        vm.useKey(true);vm.pick(DocSlot.KEY,uri("test.stegkey"));settle()
        vm.run();settle();assertNull(vm.state.value.error)
        Credential.keyFile(key).use{c->
            val decoded=StegEngine().decode(vm.state.value.result!!.staged!!.readBytes(),c)
            assertEquals("one.txt",decoded.filename);assertArrayEquals(bytes[0],decoded.data)
        }
    }
}
