package com.moyle.steg.core

import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.RandomAccessFile
import java.nio.file.Files

/** Synthetic capture regression; provide a writable test directory explicitly. */
object CaptureRegression {
    private var passed=0
    private fun test(name: String,block: () -> Unit) { block();passed++;println("PASS $name") }
    private fun rejects(expected: String?=null,block: () -> Unit) {
        try { block();error("Expected capture to be rejected") }
        catch(e: StegException) { if(expected!=null)check(e.message.orEmpty().contains(expected)) { e.toString() } }
    }
    private class TrackedInput(bytes: ByteArray,private val chunk: Int=65536) : ByteArrayInputStream(bytes) {
        var closed=false
        override fun read(b: ByteArray,off: Int,len: Int): Int = super.read(b,off,minOf(len,chunk))
        override fun close() { closed=true;super.close() }
    }
    private fun captureTwice(first: ByteArray,second: ByteArray,limit: Int,control: Control=Control()): ByteArray {
        val streams=mutableListOf<TrackedInput>()
        try {
            return BoundedIo.readStable({
                TrackedInput(if(streams.isEmpty())first else second).also { streams+=it }
            },limit,control)
        } finally { check(streams.all { it.closed }) { "Every opened input must close on success and failure" } }
    }

    @JvmStatic fun main(args: Array<String>) {
        require(args.size == 1) { "Pass a dedicated synthetic test directory." }
        val dir=File(args[0]).apply { mkdirs() }
        val source=File(dir,"changing-source.bin")
        for(preserveTime in listOf(false,true))test("rejects mixed source version, restored timestamp=$preserveTime") {
            source.writeBytes(ByteArray(2*1024*1024) { 65 })
            val beforeTime=Files.getLastModifiedTime(source.toPath())
            var changed=false
            val control=Control(progress={ stage,completed,_ ->
                if(stage=="读取文件" && completed>=65536 && !changed) {
                    changed=true
                    RandomAccessFile(source,"rw").use { it.write(ByteArray(2*1024*1024) { 66 }) }
                    if(preserveTime)Files.setLastModifiedTime(source.toPath(),beforeTime)
                }
            })
            rejects("文件发生变化") { BoundedIo.readStable({ source.inputStream() },2*1024*1024,control) }
            check(changed)
        }
        for(size in listOf(0,1,65536,65537,2*1024*1024))test("stable exact bytes at size $size") {
            val bytes=ByteArray(size) { (it*17).toByte() }
            check(captureTwice(bytes,bytes,maxOf(1,size)).contentEquals(bytes))
        }
        test("different stream chunk sizes compare identically") {
            val bytes=ByteArray(100000) { (it*13).toByte() }
            val streams=mutableListOf<TrackedInput>()
            val result=BoundedIo.readStable({
                TrackedInput(bytes,if(streams.isEmpty())7 else 4093).also { streams+=it }
            },bytes.size)
            check(result.contentEquals(bytes) && streams.size==2 && streams.all { it.closed })
        }
        test("rejects equal-length replacement between opens") {
            rejects("文件发生变化") { captureTwice(byteArrayOf(1,2,3),byteArrayOf(1,9,3),8) }
        }
        test("rejects truncation on reread") {
            rejects("文件发生变化") { captureTwice(byteArrayOf(1,2,3),byteArrayOf(1,2),8) }
        }
        test("rejects empty reread") {
            rejects("文件发生变化") { captureTwice(byteArrayOf(1),byteArrayOf(),8) }
        }
        test("rejects growth within budget") {
            rejects("文件发生变化") { captureTwice(byteArrayOf(1,2),byteArrayOf(1,2,3),8) }
        }
        test("rejects growth beyond budget") {
            rejects("超过读取预算") { captureTwice(byteArrayOf(1,2),byteArrayOf(1,2,3),2) }
        }
        test("rejects first read beyond budget") {
            rejects("超过读取预算") { captureTwice(byteArrayOf(1,2,3),byteArrayOf(1,2,3),2) }
        }
        test("rejects nonpositive budget before opening") {
            var opens=0
            rejects("读取预算无效") { BoundedIo.readStable({ opens++;ByteArrayInputStream(byteArrayOf()) },0) }
            check(opens==0)
        }
        test("cancel before open does not access input") {
            var opens=0
            rejects("已取消") { BoundedIo.readStable({ opens++;ByteArrayInputStream(byteArrayOf()) },1,Control(cancelled={true})) }
            check(opens==0)
        }
        for(cancelStage in listOf("读取文件","核对输入一致性"))test("cancels and closes input during $cancelStage") {
            var cancelled=false
            val bytes=ByteArray(200000) { 65 }
            val control=Control(progress={stage,_,_->if(stage==cancelStage)cancelled=true},cancelled={cancelled})
            rejects("已取消") { captureTwice(bytes,bytes,bytes.size,control) }
            check(cancelled)
        }
        test("rejects edits during the comparison pass") {
            source.writeBytes(ByteArray(200000) { 65 })
            var changed=false
            val control=Control(progress={stage,_,_->
                if(stage=="核对输入一致性" && !changed) {
                    changed=true
                    RandomAccessFile(source,"rw").use { it.seek(65536);it.write(ByteArray(200000-65536) { 66 }) }
                }
            })
            rejects("文件发生变化") { BoundedIo.readStable({source.inputStream()},200000,control) }
            check(changed)
        }
        test("a single-open provider is rejected with recovery advice") {
            val first=TrackedInput(byteArrayOf(1,2,3));var opens=0
            rejects("完整保存到本机") { BoundedIo.readStable({ if(opens++==0)first else throw IOException("Synthetic single-open provider") },8) }
            check(first.closed && opens==2)
        }
        for(badPass in listOf(1,2))test("rejects stalled provider on pass $badPass") {
            var opens=0;var closes=0
            rejects("无法继续") {
                BoundedIo.readStable({
                    opens++
                    if(opens==badPass)object: InputStream() {
                        override fun read(): Int=0
                        override fun read(b: ByteArray,off: Int,len: Int): Int=0
                        override fun close() { closes++ }
                    } else object: ByteArrayInputStream(byteArrayOf(1)) {
                        override fun close() { closes++;super.close() }
                    }
                },8)
            }
            check(opens==closes)
        }
        test("reread IO failure closes both streams") {
            var opens=0;var closes=0
            try {
                BoundedIo.readStable({
                    opens++
                    if(opens==2)object: InputStream() {
                        override fun read(): Int=throw IOException("Synthetic reread failure")
                        override fun close() { closes++ }
                    } else object: ByteArrayInputStream(byteArrayOf(1)) {
                        override fun close() { closes++;super.close() }
                    }
                },8)
                error("Expected synthetic IO failure")
            } catch(_: IOException) { check(opens==2 && closes==2) }
        }
        for(operation in listOf("read","hash"))test("$operation clears its buffer after an IO failure") {
            var observed: ByteArray?=null;var reads=0
            val input=object: InputStream() {
                override fun read(): Int=error("Use the buffered overload")
                override fun read(b: ByteArray,off: Int,len: Int): Int {
                    observed=b
                    if(reads++>0)throw IOException("Synthetic read failure")
                    b[off]=65
                    return 1
                }
            }
            try {
                if(operation=="read")BoundedIo.read(input,8) else BoundedIo.hash(input,8)
                error("Expected synthetic read failure")
            } catch(_: IOException) { check(observed!=null && observed!!.all { it==0.toByte() }) }
        }
        test("comparison clears its buffer after detecting a changed byte") {
            var observed: ByteArray?=null;var opens=0
            rejects("文件发生变化") {
                BoundedIo.readStable({
                    if(opens++==0)ByteArrayInputStream(byteArrayOf(65)) else object: InputStream() {
                        override fun read(): Int=error("Use the buffered overload")
                        override fun read(b: ByteArray,off: Int,len: Int): Int {
                            observed=b;b[off]=66;return 1
                        }
                    }
                },8)
            }
            check(observed!=null && observed!!.all { it==0.toByte() })
        }
        println("$passed capture checks passed")
    }
}
