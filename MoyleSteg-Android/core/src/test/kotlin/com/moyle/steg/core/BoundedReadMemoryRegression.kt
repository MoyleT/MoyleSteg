package com.moyle.steg.core

import java.io.InputStream

/** Synthetic streams only. Run each scenario in its own -Xmx64m JVM. */
object BoundedReadMemoryRegression {
    private const val MiB = 1024 * 1024

    private class GeneratedInput(private val length: Int, private val onEof: () -> Unit = {}) : InputStream() {
        var readBytes = 0
        var closed = false
        private var eofReported = false
        override fun read(): Int {
            val single = ByteArray(1)
            return if (read(single, 0, 1) < 0) -1 else single[0].toInt() and 255
        }
        override fun read(bytes: ByteArray, offset: Int, count: Int): Int {
            if (count == 0) return 0
            if (readBytes == length) {
                if (!eofReported) { eofReported = true; onEof() }
                return -1
            }
            val n = minOf(count, length - readBytes)
            for (i in 0 until n) bytes[offset + i] = ((readBytes + i) * 17).toByte()
            readBytes += n
            return n
        }
        override fun close() { closed = true }
    }

    private fun resourceRejection(stage: String, action: () -> Unit) {
        try { action() }
        catch (error: StegException) {
            check("预算" in error.message.orEmpty()) { "unrelated rejection: ${error.message}" }
            check(stage in error.message.orEmpty()) { "wrong allocation stage: ${error.message}" }
            return
        }
        catch (error: OutOfMemoryError) {
            throw AssertionError("heap exhausted before a controlled allocation admission", error)
        }
        error("missing allocation admission for $stage")
    }

    @JvmStatic fun main(args: Array<String>) {
        when (args.single()) {
            "growth" -> {
                val input = GeneratedInput(48 * MiB)
                resourceRejection("扩容") { BoundedIo.read(input, 48 * MiB) }
                check(input.readBytes in 65537 until 48 * MiB)
                check(!input.closed) { "read must not close a borrowed stream" }
                input.close()
            }
            "copy" -> {
                var resident: ByteArray? = null
                val input = GeneratedInput(16 * MiB) {
                    // Introduce pressure after the capture buffer is complete,
                    // immediately before toByteArray needs another full copy.
                    resident = ByteArray(36 * MiB) { 90 }
                }
                resourceRejection("复制") { BoundedIo.read(input, 16 * MiB) }
                check(input.readBytes == 16 * MiB && resident!!.last() == 90.toByte())
                check(!input.closed)
                resident!!.fill(0); input.close()
            }
            "initial" -> {
                val resident = ByteArray(50 * MiB) { 7 }
                val input = GeneratedInput(1)
                resourceRejection("读取") { BoundedIo.read(input, 1) }
                check(input.readBytes == 0 && resident.last() == 7.toByte())
                resident.fill(0); input.close()
            }
            "normal" -> {
                for (length in listOf(0, 1, 65536, 65537, 2 * MiB)) {
                    val streams = mutableListOf<GeneratedInput>()
                    val bytes = BoundedIo.readStable({ GeneratedInput(length).also(streams::add) }, maxOf(1, length))
                    check(bytes.size == length && bytes.indices.all { bytes[it] == (it * 17).toByte() })
                    check(streams.size == 2 && streams.all { it.closed })
                    bytes.fill(0)
                }
            }
            "cancel" -> {
                var cancelled = false
                val streams = mutableListOf<GeneratedInput>()
                try {
                    BoundedIo.readStable({ GeneratedInput(2 * MiB).also(streams::add) }, 2 * MiB,
                        Control(progress = { _, _, _ -> cancelled = true }, cancelled = { cancelled }))
                    error("cancelled capture was accepted")
                } catch (_: CancelledException) { }
                check(streams.size == 1 && streams.single().closed && streams.single().readBytes == 65536)
            }
            else -> error("Unknown bounded-read scenario")
        }
        println("PASS bounded-read ${args.single()}; maxHeap=${Runtime.getRuntime().maxMemory()}")
    }
}
