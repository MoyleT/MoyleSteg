package com.moyle.steg.android

import android.app.Application
import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import com.moyle.steg.core.*
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest

class MoyleApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // One Android process; remove remnants from a previously killed process.
        File(noBackupFilesDir,"moyle-work").deleteRecursively()
    }
}

data class PickedDocument(val uri: Uri,val name: String)
/** Header information is an unverified estimate, never a decoder or authentication result. */
data class DocumentProbe(val size: Long?,val format: String,val width: Int?=null,val height: Int?=null)

class DocumentStore(
    private val app: Application,
    private val privateSpace: (File) -> Long = { it.usableSpace }
) {
    private data class InputMetadata(val size: Long?,val modified: Long?)
    private data class DiskDigest(val hash: String,val size: Long)
    private val resolver: ContentResolver get()=app.contentResolver
    private val work: File get()=workDirectory()
    fun workDirectory(): File = File(app.noBackupFilesDir,"moyle-work").apply {
        if(!isDirectory && !mkdirs())throw StegException("无法创建应用私有工作目录。")
    }
    fun availablePrivateBytes(): Long = privateSpace(workDirectory()).coerceAtLeast(0L)
    fun describe(uri: Uri): PickedDocument {
        var name="document.bin"
        resolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { c ->
            if(c.moveToFirst()) { val i=c.getColumnIndex(OpenableColumns.DISPLAY_NAME);if(i>=0 && !c.isNull(i))name=c.getString(i).take(1024) }
        }
        return PickedDocument(uri,name)
    }
    /** Provider metadata supplements content comparison; missing columns are not proof of stability. */
    private fun metadata(uri: Uri): InputMetadata {
        fun query(columns: Array<String>): InputMetadata? = try {
            resolver.query(uri,columns,null,null,null)?.use { c ->
                if(!c.moveToFirst())null else {
                    fun number(column: String): Long? {
                        val index=c.getColumnIndex(column)
                        return if(index<0 || c.isNull(index))null else c.getLong(index).takeIf { it>=0 }
                    }
                    InputMetadata(number(OpenableColumns.SIZE),
                        number(DocumentsContract.Document.COLUMN_LAST_MODIFIED)?.takeIf { it>0 })
                }
            }
        } catch(_: Exception) { null }
        return query(arrayOf(OpenableColumns.SIZE,DocumentsContract.Document.COLUMN_LAST_MODIFIED))
            ?: query(arrayOf(OpenableColumns.SIZE)) ?: InputMetadata(null,null)
    }
    /** Read at most 54 bytes, without allocating pixels or trusting the filename suffix. */
    fun probe(doc: PickedDocument,control: Control): DocumentProbe {
        control.check()
        val size=metadata(doc.uri).size
        val header=ByteArray(54)
        var count=0
        try {
            (resolver.openInputStream(doc.uri) ?: throw StegException("无法打开文档，请重新选择。")).use { input ->
                while(count<header.size) {
                    control.check()
                    val n=input.read(header,count,header.size-count)
                    if(n<0)break
                    if(n==0)throw StegException("文档提供方返回了无法继续的读取结果。")
                    count+=n
                }
            }
            control.check()
            return probeBytes(header,size,count)
        } finally { header.fill(0) }
    }
    /** Reuse the header parser on the exact captured bytes, without another provider read. */
    internal fun probeBytes(header:ByteArray,size:Long?=header.size.toLong(),count:Int=minOf(54,header.size)):DocumentProbe {
            fun prefix(bytes: ByteArray): Boolean = count>=bytes.size && bytes.indices.all { header[it]==bytes[it] }
            val png=prefix(byteArrayOf(-119,80,78,71,13,10,26,10))
            val gif=prefix("GIF87a".toByteArray(Charsets.US_ASCII)) || prefix("GIF89a".toByteArray(Charsets.US_ASCII))
            var width: Int?=null
            var height: Int?=null
            if(png && count>=24 && ByteBuffer.wrap(header).getInt(8)==13 &&
                header.copyOfRange(12,16).contentEquals("IHDR".toByteArray(Charsets.US_ASCII))) {
                val w=ByteBuffer.wrap(header).getInt(16)
                val h=ByteBuffer.wrap(header).getInt(20)
                if(w>0 && h>0) { width=w;height=h }
            } else if(gif && count>=10) {
                val w=(header[6].toInt() and 255) or ((header[7].toInt() and 255) shl 8)
                val h=(header[8].toInt() and 255) or ((header[9].toInt() and 255) shl 8)
                if(w>0 && h>0) { width=w;height=h }
            }
            val format=when {
                png->"png"
                gif->"gif"
                prefix("SGAES001".toByteArray(Charsets.US_ASCII))->"saes"
                else->"file"
            }
            return DocumentProbe(size,format,width,height)
    }

    /**
     * Caller owns the returned private file and must delete it in finally. Two source
     * observations detect visible changes, including unchanged size/mtime; they are
     * not an OS snapshot or a guarantee against an adversarial document provider.
     */
    fun captureFile(doc: PickedDocument,limit: Long,control: Control): File {
        control.check()
        if(limit<=0)throw StegException("读取预算无效。")
        val before=metadata(doc.uri)
        if(before.size!=null && before.size>limit)
            throw StegException("文件超过读取预算；请勿为恢复而缩放隐写图。")
        ensurePrivateSpace(before.size ?: 0L)
        val captured=File.createTempFile("moyle-",".work",workDirectory())
        try {
            val first=FileOutputStream(captured).use { output ->
                val digest=(resolver.openInputStream(doc.uri) ?: throw StegException("无法打开文档，请重新选择。"))
                    .use { input -> digestStream(input,limit,control,"读取文件",before.size ?: 0L,output) { done,pending ->
                        ensurePrivateSpace(maxOf(pending.toLong(),before.size?.let { maxOf(0L,it-done) } ?: 0L))
                    } }
                output.fd.sync()
                digest
            }
            control.check()
            val reopened=try {
                resolver.openInputStream(doc.uri) ?: throw StegException("无法打开文档，请重新选择。")
            } catch(e: Exception) {
                if(e is CancelledException || e is java.util.concurrent.CancellationException)throw e
                throw StegException("无法重新读取文档以核对输入一致性。请先将文件完整保存到本机，再重新选择。",e)
            }
            val second=reopened.use { digestStream(it,limit,control,"核对输入一致性",first.size) }
            if(first!=second)throw StegException("读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
            val saved=captured.inputStream().use { digestStream(it,limit,control,"回读私有文件",first.size) }
            if(saved!=first || captured.length()!=first.size)throw StegException("私有工作文件保存后校验失败。")
            val after=metadata(doc.uri)
            if((before.size!=null && before.size!=first.size) ||
                (after.size!=null && after.size!=first.size) ||
                (before.modified!=null && after.modified!=null && before.modified!=after.modified))
                throw StegException("读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
            control.check()
            return captured
        } catch(e: Throwable) { captured.delete();throw e }
    }

    private fun ensurePrivateSpace(bytesPending: Long) {
        val reserve=32L*1024*1024
        val available=availablePrivateBytes()
        // Subtract only after checking the reserve, avoiding size + reserve overflow.
        if(available<reserve || bytesPending>available-reserve)throw StegException("应用私有空间不足。")
    }

    /** Keep disk lengths as Long; only Control's existing Int UI boundary is scaled. */
    private fun reportDiskProgress(control: Control,stage: String,done: Long,total: Long,limit: Long) {
        val extent=maxOf(total,limit)
        val largest=Int.MAX_VALUE.toLong()
        val scale=maxOf(1L,extent/largest + if(extent%largest==0L)0L else 1L)
        control.report(stage,(done/scale).toInt(),(total/scale).toInt())
    }

    /** Shared 64 KiB copy/hash loop. The owner closes the borrowed streams. */
    private fun digestStream(input: InputStream,limit: Long,control: Control,stage: String,total: Long,
        output: OutputStream?=null,beforeWrite: (Long,Int) -> Unit = { _,_ -> }): DiskDigest {
        if(limit<0)throw StegException("读取预算无效。")
        val digest=MessageDigest.getInstance("SHA-256")
        val buffer=ByteArray(65536)
        var size=0L
        try {
            while(true) {
                control.check()
                val remaining=limit-size
                // Read one sentinel byte at the limit, without overflowing Long.MAX_VALUE.
                val requested=if(remaining>=buffer.size)buffer.size else (remaining+1L).toInt()
                val n=input.read(buffer,0,requested)
                if(n<0)break
                if(n==0)throw StegException("文档提供方返回了无法继续的读取结果。")
                if(n.toLong()>remaining)throw StegException("文件超过读取预算或长度不符；请勿为恢复而缩放隐写图。")
                if(output!=null) { beforeWrite(size,n);output.write(buffer,0,n) }
                digest.update(buffer,0,n)
                size+=n.toLong()
                reportDiskProgress(control,stage,size,total,limit)
            }
            control.check()
            return DiskDigest(digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) },size)
        } finally { buffer.fill(0) }
    }
    fun capture(doc: PickedDocument,limit: Int,control: Control): ByteArray {
        control.check()
        val before=metadata(doc.uri)
        if(before.size!=null && before.size>limit)
            throw StegException("文件超过读取预算；请勿为恢复而缩放隐写图。")
        val captured=BoundedIo.readStable({
            resolver.openInputStream(doc.uri) ?: throw StegException("无法打开文档，请重新选择。")
        },limit,control)
        try {
            control.check()
            val after=metadata(doc.uri)
            if((before.size!=null && before.size!=captured.size.toLong()) ||
                (after.size!=null && after.size!=captured.size.toLong()) ||
                (before.modified!=null && after.modified!=null && before.modified!=after.modified))
                throw StegException("读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
            control.check()
            return captured
        } catch(e: Throwable) { captured.fill(0);throw e }
    }
    fun stage(data: ByteArray,control: Control): File {
        val dir=work
        if(dir.usableSpace < data.size.toLong()+16*1024*1024)throw StegException("应用私有空间不足。")
        val f=File.createTempFile("moyle-",".work",dir)
        try {
            FileOutputStream(f).use { output ->
                var at=0
                while(at<data.size){control.check();val n=minOf(65536,data.size-at);output.write(data,at,n);at+=n}
                output.fd.sync()
            }
            val (hash,size)=f.inputStream().use{BoundedIo.hash(it,maxOf(1,data.size),control)}
            if(hash!=sha256(data) || size!=data.size)throw StegException("私有工作文件保存后校验失败。")
            return f
        }catch(e: Exception){f.delete();throw e}
    }
    fun sameDocument(a: Uri,b: Uri): Boolean {
        if(a==b)return true
        return try{a.authority==b.authority && DocumentsContract.getDocumentId(a)==DocumentsContract.getDocumentId(b)}catch(_: Exception){false}
    }
    /** Validate the private result before asking any provider to create/write output. */
    fun validateStaged(file: File,expectedHash: String,control: Control) {
        control.check()
        val size=file.length()
        val maximum=1024L*1024*1024 + 1024L*1024
        if(size>maximum)throw StegException("待保存的私有文件超过输出预算。")
        val observed=file.inputStream().use { digestStream(it,size,control,"核对待保存文件",size) }
        if(observed.hash!=expectedHash || observed.size!=size || file.length()!=size)
            throw StegException("待保存的私有文件已改变，已拒绝导出。")
        control.check()
    }
    /** Only export to a newly-created empty document. No silent overwrite fallback. */
    fun export(file: File,destination: Uri,protected: List<Uri>,expectedHash: String,control: Control) {
        if(protected.any { sameDocument(it,destination) })throw StegException("保存位置不能是输入文件、载体或密钥。")
        val empty=(resolver.openInputStream(destination) ?: throw StegException("保存位置无法回读，不能验证导出。"))
            .use { it.read()<0 }
        if(!empty)throw StegException("目标不是新建空文件；为避免误覆盖，已拒绝保存。")
        val expectedSize=file.length()
        var started=false
        try {
            control.check()
            resolver.openOutputStream(destination,"wt")?.use { output ->
                started=true
                val copied=file.inputStream().use { digestStream(it,expectedSize,control,"保存文件",expectedSize,output) }
                if(copied.hash!=expectedHash || copied.size!=expectedSize)
                    throw StegException("待保存的私有文件已改变，已拒绝导出。")
                output.flush()
            } ?: throw StegException("无法写入保存位置。")
            val saved=(resolver.openInputStream(destination) ?: throw StegException("无法回读输出。"))
                .use {digestStream(it,expectedSize,control,"回读验证",expectedSize)}
            if(saved.hash!=expectedHash || saved.size!=expectedSize)throw StegException("导出后的文件与已验证成品不一致。")
            control.check()
        }catch(e: Exception){
            val removed=if(started)runCatching{DocumentsContract.deleteDocument(resolver,destination)}.getOrDefault(false) else true
            if(!removed)throw StegException("保存未完成，且提供方不允许清理部分输出。请在所选目录检查并删除不完整文件。",e)
            throw e
        }
    }
}
