package com.moyle.steg.core

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.zip.CRC32
import java.util.zip.Deflater
import java.util.zip.Inflater
import java.util.zip.DataFormatException
import kotlin.math.abs

/**
 * Deliberately narrow PNG codec: non-interlaced 8-bit RGB/RGBA only.
 * Decodes raw sample values, not display pixels; alpha-zero RGB is retained.
 * All five standard filters supported; no color-management transformation.
 * Unsupported modes explicitly reject rather than lossy fallback through Bitmap.
 */
object PngCodec {
    private val signature=byteArrayOf(137.toByte(),80,78,71,13,10,26,10)
    private const val bufferOverhead = 1024L * 1024
    fun isPng(bytes: ByteArray): Boolean = bytes.size>=8 && bytes.copyOfRange(0,8).contentEquals(signature)
    fun dimensions(bytes: ByteArray,limits: Limits): Pair<Int,Int> {
        demand(bytes.size<=limits.maxContainerBytes,"图片完整文件超过容器预算。")
        demand(isPng(bytes) && bytes.size>=33,"需要有效的 PNG 文件。")
        val b=ByteBuffer.wrap(bytes)
        demand(b.getInt(8)==13 && bytes.copyOfRange(12,16).contentEquals("IHDR".toByteArray()),"PNG 缺少 IHDR。")
        val w=b.getInt(16);val h=b.getInt(20)
        checkDimensions(w,h,limits)
        demand((bytes[24].toInt() and 255)==8 && bytes[25].toInt() in listOf(2,6) && bytes[26].toInt()==0 && bytes[27].toInt()==0 && bytes[28].toInt()==0,
            "首版只支持非交错、8 位 RGB／RGBA PNG；不支持调色板、灰度、16 位或交错 PNG。请勿为提取而转换已有隐写图。")
        val channels = if (bytes[25].toInt() == 6) 4 else 3
        checkRow(w.toLong() * channels + 1, limits)
        // Include encoded input, IDAT buffer growth/copy, RGBA output, and two reused rows.
        val working = 4L * bytes.size + w.toLong() * h * 4 + 2L * (w.toLong() * channels + 1) + bufferOverhead
        val stage="PNG ${w}×${h}（${w.toLong()*h} 像素）解码"
        MemoryChecks.requireWorking(working,limits,stage)
        MemoryChecks.checkAdditional(working-bytes.size,stage)
        return w to h
    }
    private fun checkDimensions(w: Int,h: Int,limits: Limits) {
        demand(w>0 && h>0,"PNG 尺寸 ${w}×${h} 无效。")
        demand(w.toLong()*h<=limits.maxPixels.toLong(),
            "PNG ${w}×${h} 共 ${w.toLong()*h} 像素，超过像素预算 ${limits.maxPixels}。请提高可用预算或换用内存充足的设备恢复原文件。")
    }
    private fun checkRow(bytes: Long, limits: Limits) {
        demand(bytes <= limits.maxPngRowBytes.toLong(), "PNG 单行需要 $bytes 字节，超过单行预算 ${limits.maxPngRowBytes} 字节。")
    }
    private fun checkWorking(bytes: Long, limits: Limits) {
        MemoryChecks.requireWorking(bytes,limits,"PNG 解码／编码缓冲")
    }
    private fun checkAvailableHeap(additional: Long) {
        MemoryChecks.checkAdditional(additional,"PNG 解码／编码缓冲")
    }
    fun decode(bytes: ByteArray,limits: Limits=Limits(),control: Control=Control()): RgbaImage {
        val (w,h)=dimensions(bytes,limits);val channels=if(bytes[25].toInt()==6)4 else 3
        val compressed=ByteArrayOutputStream();var pos=8;var hasHeader=false;var hasData=false;var endedData=false;var ended=false
        var transparency: IntArray?=null
        while(pos<bytes.size){
            control.check();demand(bytes.size-pos>=12,"PNG 块被截断。")
            val len=ByteBuffer.wrap(bytes,pos,4).int
            demand(len>=0 && pos.toLong()+12+len<=bytes.size.toLong(),"PNG 块长度无效。")
            val typeBytes=bytes.copyOfRange(pos+4,pos+8)
            demand(typeBytes.all { (it.toInt() and 255) in 65..90 || (it.toInt() and 255) in 97..122 },"PNG 块类型无效。")
            val type=String(typeBytes,Charsets.US_ASCII)
            val crc=CRC32().apply{update(bytes,pos+4,len+4)}.value.toInt()
            demand(crc==ByteBuffer.wrap(bytes,pos+8+len,4).int,"PNG 块 CRC 校验失败。")
            when(type){
                "IHDR"->{demand(!hasHeader && pos==8 && len==13,"PNG 头部重复或无效。");hasHeader=true}
                "IDAT"->{demand(hasHeader && !endedData,"PNG IDAT 顺序无效。");hasData=true;compressed.write(bytes,pos+8,len)}
                "IEND"->{demand(hasData && len==0,"PNG IEND 无效。");ended=true}
                "tRNS"->{
                    demand(!hasData && channels==3 && len==6 && transparency==null,"PNG 透明度块无效。")
                    val b=ByteBuffer.wrap(bytes,pos+8,len);transparency=IntArray(3){b.short.toInt() and 65535}
                }
                "acTL","fcTL","fdAT"->throw StegException("首版不支持动画 PNG。")
                "PLTE"->{demand(!hasData && len in 3..768 && len%3==0,"PNG 调色提示块无效。")}
                else->demand(typeBytes[0].toInt() and 32 != 0,"不支持的 PNG 必需块：$type")
            }
            if(hasData && type!="IDAT")endedData=true
            pos+=len+12
            if(ended)break
        }
        demand(ended && compressed.size()>0,"PNG 不完整。")
        // Extra bytes after IEND are not interpreted; whole-container hash still covers them.
        val stride=w*channels
        checkAvailableHeap(w.toLong()*h*4 + 2L*(stride+1) + compressed.size() + bufferOverhead)
        val raw=ByteArray(w*h*4);var previous=ByteArray(stride+1);var scan=ByteArray(stride+1)
        val z=Inflater()
        try {
            z.setInput(compressed.toByteArray())
            for(y in 0 until h){
                if(y%32==0)control.report("读取 PNG 像素",y,h)
                var filled=0
                while(filled<scan.size){
                    control.check();val n=z.inflate(scan,filled,scan.size-filled)
                    demand(n>0,"PNG 像素流被截断。");filled+=n
                }
                val filter=scan[0].toInt() and 255;demand(filter in 0..4,"PNG 过滤器无效。")
                // Unfilter in place. Swap these two rows instead of allocating a third per row.
                for(i in 0 until stride){
                    val left=if(i>=channels)scan[i-channels+1].toInt() and 255 else 0
                    val up=previous[i+1].toInt() and 255
                    val upperLeft=if(i>=channels)previous[i-channels+1].toInt() and 255 else 0
                    val predict=when(filter){0->0;1->left;2->up;3->(left+up)/2;else->paeth(left,up,upperLeft)}
                    scan[i+1]=((scan[i+1].toInt() and 255)+predict).toByte()
                }
                for(x in 0 until w){
                    val src=x*channels+1;val dst=(y*w+x)*4
                    raw[dst]=scan[src];raw[dst+1]=scan[src+1];raw[dst+2]=scan[src+2]
                    val t=transparency
                    raw[dst+3]=if(channels==4)scan[src+3] else if(t!=null && (scan[src].toInt() and 255)==t[0] && (scan[src+1].toInt() and 255)==t[1] && (scan[src+2].toInt() and 255)==t[2])0 else 255.toByte()
                }
                val oldPrevious=previous;previous=scan;scan=oldPrevious
            }
            val extra=ByteArray(1);val n=z.inflate(extra)
            demand(n==0 && z.finished() && z.remaining==0 && !z.needsDictionary(),"PNG 像素流超长或有异常压缩尾部。")
            control.report("读取 PNG 像素",h,h)
            return RgbaImage(w,h,raw)
        }catch(e: DataFormatException){raw.fill(0);throw StegException("PNG 压缩流损坏。",e)}
        catch(e: Exception){raw.fill(0);throw e}
        finally{previous.fill(0);scan.fill(0);z.end()}
    }
    fun encode(image: RgbaImage,limits: Limits=Limits(),control: Control=Control()): ByteArray {
        checkDimensions(image.width,image.height,limits)
        val rowBytes=image.width.toLong()*4+1
        checkRow(rowBytes, limits)
        val fixedWorking=image.rgba.size.toLong()+rowBytes+32768+bufferOverhead
        checkWorking(fixedWorking, limits)
        checkAvailableHeap(rowBytes+32768+bufferOverhead)
        val def=Deflater(6);val compressed=ByteArrayOutputStream();val buf=ByteArray(32768)
        fun drain(finish: Boolean){
            while(if(finish)!def.finished() else !def.needsInput()){
                control.check();val n=def.deflate(buf)
                demand(compressed.size().toLong()+n+57<=limits.maxContainerBytes,"输出 PNG 超过完整容器预算。")
                // Both growable streams and their final array copies can coexist during encoding.
                checkWorking(fixedWorking+6L*(compressed.size().toLong()+n+57), limits)
                checkAvailableHeap(2L*(compressed.size().toLong()+n)+bufferOverhead)
                compressed.write(buf,0,n)
                if(n==0){demand(!finish || def.finished(),"PNG 编码器没有取得进展。");break}
            }
        }
        try{
            val stride=image.width*4;val row=ByteArray(stride+1)
            for(y in 0 until image.height){
                if(y%32==0)control.report("编码 PNG",y,image.height)
                row[0]=1 // Sub filter, exact and deterministic; no pixel transform.
                val start=y*stride
                for(i in 0 until stride){val left=if(i>=4)image.rgba[start+i-4].toInt() and 255 else 0;row[i+1]=((image.rgba[start+i].toInt() and 255)-left).toByte()}
                def.setInput(row);drain(false)
            }
            def.finish();drain(true)
        }finally{def.end()}
        checkAvailableHeap(4L*(compressed.size().toLong()+57)+bufferOverhead)
        val out=ByteArrayOutputStream().apply {write(signature)}
        fun chunk(type: String,data: ByteArray){
            val t=type.toByteArray(Charsets.US_ASCII);out.write(ByteBuffer.allocate(4).putInt(data.size).array());out.write(t);out.write(data)
            out.write(ByteBuffer.allocate(4).putInt(CRC32().apply{update(t);update(data)}.value.toInt()).array())
        }
        chunk("IHDR",ByteBuffer.allocate(13).putInt(image.width).putInt(image.height).put(8).put(6).put(0).put(0).put(0).array())
        chunk("IDAT",compressed.toByteArray());chunk("IEND",byteArrayOf())
        val result=out.toByteArray();demand(result.size<=limits.maxContainerBytes,"输出 PNG 超过预算。")
        return result
    }
    private fun paeth(a: Int,b: Int,c: Int): Int {val p=a+b-c;val pa=abs(p-a);val pb=abs(p-b);val pc=abs(p-c);return if(pa<=pb && pa<=pc)a else if(pb<=pc)b else c}
}
