package com.moyle.steg.core

import java.io.InputStream
import java.security.MessageDigest

/** Unknown advertised sizes do not bypass the cap. */
object BoundedIo {
    private class WipingBuffer(size: Int, private val maximum: Int) {
        private var buffer = ByteArray(size)
        private var count = 0
        fun size(): Int = count
        fun write(bytes: ByteArray, offset: Int, length: Int) {
            val required = count.toLong() + length
            demand(required <= maximum, "文件超过读取预算；请勿为恢复而缩放隐写图。")
            if (required > buffer.size) {
                val capacity = minOf(maximum.toLong(), maxOf(required, 2L * buffer.size)).toInt()
                // The old buffer stays live during copying. Admit the entire new
                // allocation, not just the capacity difference, without forcing GC.
                MemoryChecks.checkAdditional(capacity.toLong() + MemoryChecks.BUFFER_OVERHEAD, "读取文件缓冲扩容")
                val previous = buffer
                buffer = previous.copyOf(capacity)
                previous.fill(0)
            }
            bytes.copyInto(buffer, count, offset, offset + length)
            count += length
        }
        fun toByteArray(): ByteArray {
            MemoryChecks.checkAdditional(count.toLong() + MemoryChecks.BUFFER_OVERHEAD, "复制已读取文件")
            return buffer.copyOf(count)
        }
        fun wipe() { buffer.fill(0); count = 0 }
    }

    /** Single bounded read; the caller retains ownership of the borrowed input. */
    fun read(input: InputStream,limit: Int,control: Control=Control()): ByteArray {
        demand(limit>0,"读取预算无效。")
        control.check()
        val initialSize=minOf(limit,65536)
        val readSize=minOf(65536L,limit.toLong()+1).toInt()
        MemoryChecks.checkAdditional(initialSize.toLong()+readSize+MemoryChecks.BUFFER_OVERHEAD,"读取文件")
        val out=WipingBuffer(initialSize,limit);val buf=ByteArray(readSize)
        try {
            while(true){
                control.check();val requested=minOf(buf.size.toLong(),limit.toLong()-out.size()+1).toInt()
                val n=input.read(buf,0,requested)
                if(n<0)break
                demand(n>0,"文档提供方返回了无法继续的读取结果。")
                demand(out.size().toLong()+n<=limit,"文件超过读取预算；请勿为恢复而缩放隐写图。")
                out.write(buf,0,n);control.report("读取文件",out.size(),0)
            }
            return out.toByteArray()
        }finally{buf.fill(0);out.wipe()}
    }

    /**
     * Owns and closes each opened stream. Captures bounded bytes, then reopens the
     * document and compares every byte before returning that same captured array.
     * This detects observable concurrent changes, including preserved timestamps;
     * it is not an OS snapshot or a guarantee against an adversarial provider.
     * Providers that cannot reopen a document must supply a stable local export.
     */
    fun readStable(opener: () -> InputStream,limit: Int,control: Control=Control()): ByteArray {
        demand(limit>0,"读取预算无效。")
        control.check()
        val captured=opener().use { read(it,limit,control) }
        var comparisonBuffer: ByteArray?=null
        try {
            val comparisonSize=minOf(65536L,limit.toLong()+1).toInt()
            MemoryChecks.checkAdditional(comparisonSize.toLong()+MemoryChecks.BUFFER_OVERHEAD,"复核已读取文件")
            val buffer=ByteArray(comparisonSize).also { comparisonBuffer=it }
            control.check()
            val second=try { opener() } catch(e: Exception) {
                if(e is CancelledException)throw e
                throw StegException("无法重新读取文档以核对输入一致性。请先将文件完整保存到本机，再重新选择。",e)
            }
            second.use { input ->
                var at=0
                while(true) {
                    control.check()
                    val requested=minOf(buffer.size.toLong(),limit.toLong()-at+1).toInt()
                    val n=input.read(buffer,0,requested)
                    if(n<0) {
                        demand(at==captured.size,"读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
                        break
                    }
                    demand(n>0,"文档提供方返回了无法继续的读取结果。")
                    demand(at.toLong()+n<=limit,"文件超过读取预算；请勿为恢复而缩放隐写图。")
                    demand(at.toLong()+n<=captured.size,"读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
                    for(i in 0 until n) {
                        if(buffer[i]!=captured[at+i])throw StegException("读取期间文件发生变化，请等待保存、同步或下载完成后重试。")
                    }
                    at+=n
                    control.report("核对输入一致性",at,captured.size)
                }
            }
            control.check()
            return captured
        } catch(e: Throwable) {
            captured.fill(0)
            throw e
        } finally { comparisonBuffer?.fill(0) }
    }
    /** The caller retains ownership of the borrowed input. */
    fun hash(input: InputStream,limit: Int,control: Control=Control()): Pair<String,Int> {
        val digest=MessageDigest.getInstance("SHA-256");val buf=ByteArray(65536);var size=0
        demand(limit>0,"哈希预算无效。")
        try {
            while(true){
                control.check();val n=input.read(buf,0,minOf(buf.size.toLong(),limit.toLong()-size+1).toInt())
                if(n<0)break
                demand(n>0 && size.toLong()+n<=limit,"文件长度不符或超过预算。")
                digest.update(buf,0,n);size+=n;control.report("回读验证",size,0)
            }
            return digest.digest().hex() to size
        } finally { buf.fill(0) }
    }
}
