package com.moyle.steg.core

import java.io.OutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.DataFormatException
import java.util.zip.Inflater

/** PAY1 metadata is at most 56+65535 bytes. Encoded payload and decompression stay bounded. */
internal class StreamPayload(private val limits:FileLimits,private val plainLength:Long,
    private val control:Control,private val output:OutputStream?,
    private val originalSizeAdmission:(Long)->Unit = {}):AutoCloseable {
    private val fixed=ByteArray(Payload.FIXED)
    private var fixedAt=0;private var nameBytes:ByteArray?=null;private var nameAt=0
    private var filename:String?=null;private var original=0L;private var stored=0L
    private var compressed=false;private var expectedDigest=ByteArray(32)
    private var storedRead=0L;private var produced=0L
    private val digest=MessageDigest.getInstance("SHA-256")
    private var inflater:Inflater?=null
    private val buffer=ByteArray(StreamGcm.CHUNK)
    fun accept(bytes:ByteArray,offset:Int,count:Int){
        var at=offset;val end=offset+count
        while(at<end){
            control.check()
            if(fixedAt<fixed.size){
                val n=minOf(end-at,fixed.size-fixedAt);bytes.copyInto(fixed,fixedAt,at,at+n);fixedAt+=n;at+=n
                if(fixedAt==fixed.size)header()
            }else if(filename==null){
                val name=nameBytes!!;val n=minOf(end-at,name.size-nameAt)
                bytes.copyInto(name,nameAt,at,at+n);nameAt+=n;at+=n
                if(nameAt==name.size)filename=metadataFilename(decodeUtf8(name))
            }else{
                val n=end-at
                demand(storedRead+n<=stored,"PAY1 数据含多余尾部或长度不符。")
                storedRead+=n
                if(compressed)inflate(bytes,at,n)else emit(bytes,at,n)
                at=end
            }
        }
    }
    private fun header(){
        val b=ByteBuffer.wrap(fixed);val magic=ByteArray(4).also(b::get)
        demand(magic.contentEquals("PAY1".toByteArray(Charsets.US_ASCII)) && b.get().toInt()==1,"内部 PAY1 格式无效。")
        val compression=b.get().toInt();val length=b.short.toInt() and 65535
        original=b.long;stored=b.long;b.get(expectedDigest)
        demand(compression in 0..1 && original in 0..limits.maxPayloadBytes && stored in 0..limits.maxPayloadBytes,
            "内部长度或压缩方式无效／超过文件预算。")
        demand(Payload.FIXED.toLong()+length+stored==plainLength,"内部 PAY1 长度不匹配。")
        demand(length>0,"容器文件名无效。")
        compressed=compression==1
        demand(compressed || original==stored,"未压缩 PAY1 长度不匹配。")
        originalSizeAdmission(original)
        nameBytes=ByteArray(length)
        if(compressed)inflater=Inflater()
    }
    private fun emit(bytes:ByteArray,offset:Int,count:Int){
        demand(produced+count<=original && produced+count<=limits.maxPayloadBytes,"恢复内容超过声明长度或文件预算。")
        digest.update(bytes,offset,count);output?.write(bytes,offset,count);produced+=count
        control.report("校验原始内容",produced.toInt(),original.toInt())
    }
    private fun inflate(bytes:ByteArray,offset:Int,count:Int){
        val z=inflater!!
        demand(!z.finished(),"压缩数据含多余尾部。")
        z.setInput(bytes,offset,count)
        try {
            while(true){
                control.check();val n=z.inflate(buffer)
                if(n>0)emit(buffer,0,n)
                if(z.finished()){demand(z.remaining==0,"压缩流含多余尾部。");break}
                demand(!z.needsDictionary(),"压缩流不允许外部字典。")
                if(z.needsInput())break
                demand(n>0,"压缩解码没有取得进展。")
            }
        }catch(e:DataFormatException){throw StegException("压缩数据损坏。",e)}
    }
    fun finish(containerHash:String):FileResult {
        control.check()
        demand(filename!=null && storedRead==stored && produced==original,"恢复文件大小或 PAY1 长度不匹配。")
        if(compressed)demand(inflater!!.finished() && inflater!!.remaining==0 && !inflater!!.needsDictionary(),"压缩流被截断。")
        val actual=digest.digest()
        demand(MessageDigest.isEqual(expectedDigest,actual),"恢复文件 SHA-256 不匹配。")
        return FileResult(filename!!,original,stored,compressed,actual.hex(),containerHash,null)
    }
    override fun close(){fixed.fill(0);nameBytes?.fill(0);expectedDigest.fill(0);buffer.fill(0);inflater?.end()}
}
