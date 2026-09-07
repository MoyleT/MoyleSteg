package com.moyle.steg.android

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.content.res.AssetFileDescriptor
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.OperationCanceledException
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import com.moyle.steg.core.CancelledException
import com.moyle.steg.core.Control
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
import java.io.InputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** External providers are controlled; the DocumentStore and resolver are real. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class DocumentStoreSelectionCancellationTest {
    private lateinit var app:Application
    private lateinit var source:File
    private lateinit var provider:CancellableDocuments
    private lateinit var store:DocumentStore
    private val executor=Executors.newSingleThreadExecutor()
    private val uri=Uri.parse("content://selection-cancellation.test/source.bin")
    private val document get()=PickedDocument(uri,"source.bin")

    @Before fun setup(){
        app=RuntimeEnvironment.getApplication()
        source=File.createTempFile("selection-cancel-",".bin",app.cacheDir)
        source.writeBytes(ByteArray(128){it.toByte()})
        provider=CancellableDocuments(source)
        provider.attachInfo(app,ProviderInfo().apply{
            authority="selection-cancellation.test";packageName=app.packageName
            name=CancellableDocuments::class.java.name;applicationInfo=app.applicationInfo
            exported=true;grantUriPermissions=true
        })
        ShadowContentResolver.registerProviderInternal("selection-cancellation.test",provider)
        store=DocumentStore(app)
    }
    @After fun teardown(){
        provider.queryRelease.countDown();provider.openRelease.countDown()
        executor.shutdownNow()
        assertTrue("provider worker did not finish",executor.awaitTermination(5,TimeUnit.SECONDS))
        assertTrue("selection leaked a source descriptor",!source.exists() || source.delete())
    }
    private fun cancelled(action:()->Unit):Throwable{
        val error=try{action();null}catch(error:Throwable){error}
        assertTrue("expected cancellation, got $error",error is OperationCanceledException || error is CancelledException || error is java.util.concurrent.CancellationException)
        return error!!
    }

    @Test fun describeHonorsAlreadyCancelledControlBeforeProviderQuery(){
        cancelled{store.describe(uri,Control(cancelled={true}))}
        assertEquals(0,provider.queries)
        assertEquals(0,provider.opens)
    }
    @Test fun describeHonorsAlreadyCancelledSignalBeforeProviderQuery(){
        val signal=CancellationSignal().apply{cancel()}
        cancelled{store.describe(uri,Control(),signal)}
        assertEquals(0,provider.queries)
    }
    @Test fun blockedDescribeQueryReceivesProviderCancellationSignal(){
        provider.blockQuery=true
        val signal=CancellationSignal()
        val future=executor.submit<Throwable?>{try{store.describe(uri,Control(),signal);null}catch(error:Throwable){error}}
        assertTrue(provider.queryEntered.await(3,TimeUnit.SECONDS))
        signal.cancel()
        provider.queryRelease.countDown()
        val error=future.get(3,TimeUnit.SECONDS)
        assertNotNull("query did not receive a CancellationSignal",provider.lastQuerySignal)
        assertTrue("remote provider signal was not cancelled",provider.lastQuerySignal!!.isCanceled)
        assertTrue(error is OperationCanceledException || error is CancelledException)
        assertEquals(1,provider.queries)
        assertEquals(0,provider.opens)
    }
    @Test fun blockedProbeMetadataCancellationDoesNotFallBackOrOpenInput(){
        provider.blockQuery=true
        val signal=CancellationSignal()
        val future=executor.submit<Throwable?>{try{store.probe(document,Control(),signal);null}catch(error:Throwable){error}}
        assertTrue(provider.queryEntered.await(3,TimeUnit.SECONDS))
        signal.cancel();provider.queryRelease.countDown()
        val error=future.get(3,TimeUnit.SECONDS)
        assertTrue(error is OperationCanceledException || error is CancelledException)
        assertNotNull(provider.lastQuerySignal)
        assertEquals("cancelled metadata must not perform a size-only retry",1,provider.queries)
        assertEquals(0,provider.opens)
    }
    @Test fun providerCancellationIsNotSwallowedAsMissingMetadata(){
        provider.queryFailure=OperationCanceledException("provider cancelled its query")
        cancelled{store.probe(document,Control())}
        assertEquals(1,provider.queries)
        assertEquals(0,provider.opens)
    }
    @Test fun cooperativeCancellationIsNotSwallowedAsMissingMetadata(){
        provider.queryFailure=CancelledException()
        cancelled{store.probe(document,Control())}
        assertEquals(1,provider.queries)
        assertEquals(0,provider.opens)
    }
    @Test fun descriptorOpenReceivesProviderCancellationSignal(){
        provider.blockOpen=true
        val signal=CancellationSignal()
        val future=executor.submit<Throwable?>{try{store.probe(document,Control(),signal);null}catch(error:Throwable){error}}
        assertTrue(provider.openEntered.await(3,TimeUnit.SECONDS))
        signal.cancel();provider.openRelease.countDown()
        val error=future.get(3,TimeUnit.SECONDS)
        assertNotNull("asset open did not receive CancellationSignal",provider.lastOpenSignal)
        assertTrue(provider.lastOpenSignal!!.isCanceled)
        assertTrue(error is OperationCanceledException || error is CancelledException)
        assertEquals(1,provider.opens)
    }
    @Test fun cancellationWhenDescriptorReturnsClosesItBeforeReading(){
        val signal=CancellationSignal()
        provider.afterOpen={signal.cancel()}
        cancelled{store.probe(document,Control(),signal)}
        assertEquals(1,provider.opens)
        assertTrue("opened descriptor remains live after cancellation",provider.lastFileDescriptor?.valid()==false)
    }
    @Test fun cooperativeCancellationAfterFirstProbeReadClosesWithoutSecondRead(){
        val stopped=AtomicBoolean(false)
        var reads=0;var closed=false
        shadowOf(app.contentResolver).registerInputStream(uri,object:InputStream(){
            override fun read()=throw AssertionError("unexpected scalar read")
            override fun read(bytes:ByteArray,offset:Int,length:Int):Int{
                reads++;assertEquals("probe continued after cancellation",1,reads)
                bytes[offset]=65;stopped.set(true);return 1
            }
            override fun close(){closed=true}
        })
        cancelled{store.probe(document,Control(cancelled={stopped.get()}))}
        assertEquals(1,reads);assertTrue(closed)
    }
    @Test fun signalPathReadsRealDescriptorAndClosesItNormally(){
        val result=store.probe(document,Control(),CancellationSignal())
        assertEquals("file",result.format)
        assertEquals(128L,result.size)
        assertNotNull(provider.lastQuerySignal)
        assertNotNull(provider.lastOpenSignal)
        assertTrue(provider.lastFileDescriptor?.valid()==false)
    }
    @Test fun cancellationAfterQueryClosesReturnedCursor(){
        val signal=CancellationSignal()
        provider.afterQuery={signal.cancel()}
        cancelled{store.describe(uri,Control(),signal)}
        assertTrue(provider.lastCursor?.isClosed==true)
        assertEquals(0,provider.opens)
    }

    class CancellableDocuments(private val source:File):ContentProvider(){
        @Volatile var queries=0
        @Volatile var opens=0
        var blockQuery=false;var blockOpen=false
        val queryEntered=CountDownLatch(1);val queryRelease=CountDownLatch(1)
        val openEntered=CountDownLatch(1);val openRelease=CountDownLatch(1)
        @Volatile var lastQuerySignal:CancellationSignal?=null
        @Volatile var lastOpenSignal:CancellationSignal?=null
        @Volatile var lastFileDescriptor:java.io.FileDescriptor?=null
        @Volatile var lastCursor:Cursor?=null
        var queryFailure:Exception?=null
        var afterQuery:()->Unit={};var afterOpen:()->Unit={}
        override fun onCreate()=true
        override fun query(uri:Uri,projection:Array<out String>?,selection:String?,selectionArgs:Array<out String>?,sortOrder:String?):Cursor=
            query(uri,projection,selection,selectionArgs,sortOrder,null)
        override fun query(uri:Uri,projection:Array<out String>?,selection:String?,selectionArgs:Array<out String>?,sortOrder:String?,cancellationSignal:CancellationSignal?):Cursor{
            queries++;lastQuerySignal=cancellationSignal
            if(blockQuery){
                cancellationSignal?.setOnCancelListener{queryRelease.countDown()}
                queryEntered.countDown();check(queryRelease.await(5,TimeUnit.SECONDS))
                cancellationSignal?.throwIfCanceled()
            }
            queryFailure?.let{throw it}
            val columns=projection?.map{it}?.toTypedArray() ?: arrayOf(OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE)
            return MatrixCursor(columns).apply{
                addRow(columns.map<String,Any?>{when(it){OpenableColumns.DISPLAY_NAME->"source.bin";OpenableColumns.SIZE->source.length();else->null}}.toTypedArray())
                lastCursor=this;afterQuery()
            }
        }
        private fun asset(signal:CancellationSignal?):AssetFileDescriptor{
            opens++;lastOpenSignal=signal
            if(blockOpen){
                signal?.setOnCancelListener{openRelease.countDown()}
                openEntered.countDown();check(openRelease.await(5,TimeUnit.SECONDS))
                signal?.throwIfCanceled()
            }
            val descriptor=ParcelFileDescriptor.open(source,ParcelFileDescriptor.MODE_READ_ONLY)
            lastFileDescriptor=descriptor.fileDescriptor
            return AssetFileDescriptor(descriptor,0,source.length()).also{afterOpen()}
        }
        override fun openAssetFile(uri:Uri,mode:String):AssetFileDescriptor=asset(null)
        override fun openAssetFile(uri:Uri,mode:String,signal:CancellationSignal?):AssetFileDescriptor=asset(signal)
        override fun openTypedAssetFile(uri:Uri,mimeTypeFilter:String,opts:Bundle?):AssetFileDescriptor=asset(null)
        override fun openTypedAssetFile(uri:Uri,mimeTypeFilter:String,opts:Bundle?,signal:CancellationSignal?):AssetFileDescriptor=asset(signal)
        override fun openFile(uri:Uri,mode:String):ParcelFileDescriptor=asset(null).parcelFileDescriptor
        override fun getType(uri:Uri)="application/octet-stream"
        override fun insert(uri:Uri,values:ContentValues?):Uri?=null
        override fun delete(uri:Uri,selection:String?,selectionArgs:Array<out String>?)=0
        override fun update(uri:Uri,values:ContentValues?,selection:String?,selectionArgs:Array<out String>?)=0
    }
}
