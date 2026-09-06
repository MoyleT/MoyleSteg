package com.moyle.steg.core

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.Deflater

data class FileLimits(val maxPayloadBytes: Long = 1L shl 30,
                      val maxContainerBytes: Long = (1L shl 30) + 1048576L) {
    init { require(maxPayloadBytes in 1..(1L shl 30)); require(maxContainerBytes in 1..((1L shl 30)+1048576L)) }
}
data class FileResult(val filename: String, val originalBytes: Long, val storedBytes: Long,
                      val compressed: Boolean, val payloadSha256: String, val containerSha256: String,
                      val output: File?)

class SaesFiles(private val limits: FileLimits = FileLimits(), private val control: Control = Control()) {
    fun encrypt(source: File, filename: String, credential: Credential, workDirectory: File): FileResult =
        transaction(workDirectory) { work ->
            val name=utf8(safeFilename(filename))
            demand(Header.SIZE.toLong()+Payload.FIXED+name.size+16<=limits.maxContainerBytes,
                "SAES 输出预算不足以容纳头部和文件名。")
            val capture=captureSource(source,work)
            control.report("复核源文件")
            val reread=hashFile(source,limits.maxPayloadBytes,"复核源文件")
            demand(reread.first==capture.original && reread.second==capture.hash,
                "读取期间源文件发生变化；请等待保存、同步或下载完成后重试。")
            val meta=ByteBuffer.allocate(Payload.FIXED+name.size)
                .put("PAY1".toByteArray(Charsets.US_ASCII)).put(1)
                .put(if(capture.compressed)1.toByte() else 0.toByte()).putShort(name.size.toShort())
                .putLong(capture.original).putLong(capture.stored).put(capture.digest).put(name).array()
            try {
                val cipherLength=meta.size.toLong()+capture.stored+16
                demand(Header.SIZE+cipherLength<=limits.maxContainerBytes && cipherLength<=Int.MAX_VALUE,
                    "SAES 输出容器超过文件处理预算。")
                work.space(Header.SIZE+cipherLength)
                val output=work.create()
                val header=Header.create(credential.mode,Crypto.random(16),Crypto.random(12),cipherLength.toInt())
                control.report("派生密钥")
                checkDerivationMemory(credential)
                val hash=Crypto.derive(credential,header).use { keys ->
                    StreamGcm.encrypt(capture.file,meta,header,keys.encryption,output,control)
                }
                work.remove(capture.file)
                control.report("保存后独立回读验证")
                val checked=verify(output,credential,workDirectory)
                demand(checked.filename==filename && checked.originalBytes==capture.original &&
                    checked.payloadSha256==capture.hash && checked.containerSha256==hash,"SAES 保存后验证不匹配。")
                control.check();checked.copy(output=output)
            }finally{meta.fill(0);name.fill(0);capture.digest.fill(0)}
        }

    fun decrypt(container: File, credential: Credential, workDirectory: File): FileResult =
        decode(container,credential,workDirectory,true)
    fun verify(container: File, credential: Credential, workDirectory: File): FileResult =
        decode(container,credential,workDirectory,false)

    private fun decode(container:File,credential:Credential,directory:File,restore:Boolean):FileResult =
        transaction(directory) { work ->
            val captured=captureContainer(container,work)
            control.report("派生密钥")
            checkDerivationMemory(credential)
            Crypto.derive(credential,captured.header).use { keys ->
                // The first pass authenticates everything and deliberately discards all emitted plaintext.
                val first=StreamGcm.decrypt(captured.file,captured.header,keys.encryption,control,"完整认证 SAES"){_,_,_->}
                demand(first==captured.hash,"私有容器副本发生变化。")
                control.report("完整认证通过")
                // PAY1 is parsed only after whole-container authentication succeeded.
                val output=if(restore)work.create()else null
                val stream=output?.let(::FileOutputStream)
                try {
                    StreamPayload(limits,captured.header.cipherLength.toLong()-16,control,stream,
                        { original -> if(restore)work.space(original) }).use { parser ->
                        val second=StreamGcm.decrypt(captured.file,captured.header,keys.encryption,control,
                            if(restore)"流式恢复"else "只读流式验证",parser::accept)
                        demand(first==second,"两次认证读取的容器字节不一致。")
                        val result=parser.finish(second)
                        stream?.fd?.sync();control.check()
                        result.copy(output=output)
                    }
                }finally{stream?.close()}
            }
        }

    private data class Source(val file:File,val original:Long,val stored:Long,val compressed:Boolean,
                              val digest:ByteArray){val hash:String get()=digest.hex()}
    private data class Captured(val file:File,val header:Header,val hash:String)
    private fun checkDerivationMemory(credential:Credential){
        // Capture/compression can be lengthy. Re-observe the actual heap directly before KDF work.
        MemoryChecks.checkAdditional((if(credential.mode==1)40L else 2L)*1024*1024,"SAES 密钥派生")
    }
    private fun captureSource(source:File,work:Workspace):Source {
        val inputBuffer=ByteArray(StreamGcm.CHUNK);val zipBuffer=ByteArray(StreamGcm.CHUNK)
        val deflater=Deflater(9)
        try {
            FileInputStream(source).use { input ->
                val expected=input.channel.size()
                demand(expected in 0..limits.maxPayloadBytes,"秘密文件超过文件处理预算。")
                // Raw snapshot and candidate compression can each occupy at most the source size.
                work.space(expected*2+2L*StreamGcm.CHUNK)
                val raw=work.create();val zipped=work.create()
                val digest=MessageDigest.getInstance("SHA-256")
                var done=0L;var zipBytes=0L;var useful=true
                FileOutputStream(raw).use { rawOut -> FileOutputStream(zipped).use { zipOut ->
                    fun compressAvailable(){
                        while(!deflater.needsInput() || (deflater.finished().not() && done==expected)){
                            control.check();val n=deflater.deflate(zipBuffer)
                            if(n>0){zipBytes+=n;if(zipBytes<=expected && useful)zipOut.write(zipBuffer,0,n)else useful=false}
                            if(deflater.finished() || deflater.needsInput())break
                            demand(n>0,"压缩器没有取得进展。")
                        }
                    }
                    control.report("捕获与压缩源文件",0,expected.toInt())
                    while(done<expected){
                        control.check();val n=input.read(inputBuffer,0,minOf(StreamGcm.CHUNK.toLong(),expected-done).toInt())
                        demand(n>0,"读取期间源文件被截断。")
                        rawOut.write(inputBuffer,0,n);digest.update(inputBuffer,0,n)
                        deflater.setInput(inputBuffer,0,n);done+=n
                        compressAvailable();control.report("捕获与压缩源文件",done.toInt(),expected.toInt())
                    }
                    demand(input.read()<0,"读取期间源文件长度发生变化。")
                    deflater.finish()
                    while(!deflater.finished()){
                        control.check();val n=deflater.deflate(zipBuffer)
                        demand(n>0 || deflater.finished(),"压缩器没有取得进展。")
                        zipBytes+=n;if(zipBytes<=expected && useful)zipOut.write(zipBuffer,0,n)else useful=false
                    }
                    rawOut.fd.sync();zipOut.fd.sync()
                } }
                val compressed=useful && zipBytes<expected
                work.remove(if(compressed)raw else zipped)
                return Source(if(compressed)zipped else raw,expected,if(compressed)zipBytes else expected,compressed,digest.digest())
            }
        }finally{inputBuffer.fill(0);zipBuffer.fill(0);deflater.end()}
    }
    private fun captureContainer(source:File,work:Workspace):Captured {
        val buffer=ByteArray(StreamGcm.CHUNK)
        try {
            FileInputStream(source).use { input ->
                val expected=input.channel.size()
                demand(expected in Header.SIZE.toLong()..limits.maxContainerBytes,"SAES 容器长度无效或超过文件处理预算。")
                val hb=StreamGcm.exact(input,Header.SIZE)
                val header=Header.parse(hb,minOf(limits.maxPayloadBytes+Payload.FIXED+65535+16,limits.maxContainerBytes-Header.SIZE))
                demand(Header.SIZE.toLong()+header.cipherLength==expected,"SAES 文件被截断或含多余尾部。")
                work.space(expected)
                val file=work.create();val digest=MessageDigest.getInstance("SHA-256")
                FileOutputStream(file).use { output ->
                    output.write(hb);digest.update(hb);var done=Header.SIZE.toLong()
                    control.report("捕获 SAES 容器",done.toInt(),expected.toInt())
                    while(done<expected){
                        control.check();val n=input.read(buffer,0,minOf(StreamGcm.CHUNK.toLong(),expected-done).toInt())
                        demand(n>0,"SAES 容器被截断。")
                        output.write(buffer,0,n);digest.update(buffer,0,n);done+=n
                        control.report("捕获 SAES 容器",done.toInt(),expected.toInt())
                    }
                    demand(input.read()<0,"SAES 容器含多余尾部。");output.fd.sync()
                }
                return Captured(file,header,digest.digest().hex())
            }
        }finally{buffer.fill(0)}
    }
    private fun hashFile(file:File,budget:Long,stage:String):Pair<Long,String> {
        val buffer=ByteArray(StreamGcm.CHUNK);val digest=MessageDigest.getInstance("SHA-256")
        try {
            FileInputStream(file).use { input ->
                val expected=input.channel.size();demand(expected in 0..budget,"源文件超过文件处理预算。")
                var done=0L;control.report(stage,0,expected.toInt())
                while(true){
                    control.check();val n=input.read(buffer);if(n<0)break
                    demand(n>0 && done+n<=expected,"读取期间源文件长度发生变化。")
                    digest.update(buffer,0,n);done+=n;control.report(stage,done.toInt(),expected.toInt())
                }
                demand(done==expected,"读取期间源文件被截断。")
                return done to digest.digest().hex()
            }
        }finally{buffer.fill(0)}
    }
    private inline fun transaction(directory:File,body:(Workspace)->FileResult):FileResult {
        control.check();demand(directory.isDirectory,"请提供可写的私有工作目录。")
        val work=Workspace(directory);var result:FileResult?=null;var failure:Throwable?=null
        try {return body(work).also {result=it}}
        catch(e:Throwable){failure=e;throw e}
        finally {
            val cleanup=work.clean(result?.output)
            if(cleanup!=null){
                result?.output?.delete()
                if(failure!=null)failure.addSuppressed(cleanup)else throw cleanup
            }
        }
    }
    private inner class Workspace(val directory:File){
        private val files=mutableListOf<File>()
        fun space(additional:Long){
            control.check()
            demand(additional>=0 && directory.usableSpace>=additional+32L*1024*1024,
                "私有临时磁盘空间不足；需要额外工作空间并保留 32 MiB 余量。")
        }
        fun create():File {control.check();return File.createTempFile("moyle-sf-",".work",directory).also(files::add)}
        fun remove(file:File){demand(!file.exists() || file.delete(),"无法清理私有临时文件。");files.remove(file)}
        fun clean(keep:File?):StegException? {
            var failed=false
            for(file in files)if(file!=keep && file.exists())try{if(!file.delete())failed=true}catch(_:Exception){failed=true}
            return if(failed)StegException("操作未完整结束：部分私有临时文件清理失败。")else null
        }
    }
}
