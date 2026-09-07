package com.moyle.steg.core

import java.io.File
import java.io.IOException
import java.nio.file.FileSystemException
import java.util.Random

object BundleDiskRegression {
    private const val LIMIT = 4L * 1024 * 1024
    @JvmStatic fun main(args: Array<String>) {
        val root = File(args[0]).apply { mkdirs() }
        val work = File(root, "space-${System.nanoTime()}").apply { mkdirs() }
        val source = File(work, "synthetic-source.bin").apply {
            writeBytes(ByteArray(192 * 1024).also { Random(943).nextBytes(it) })
        }
        val original = sha256(source.readBytes())
        val sources = listOf(BundleSource(source, "synthetic-source.bin"))
        val reserve = BundleDiskPolicy.RESERVE_BYTES
        var passed = 0
        fun test(name: String, action: () -> Unit) { action(); passed++; println("PASS $name") }
        fun rejects(fragment: String = "空间不足", action: () -> Unit) {
            try { action(); error("Operation unexpectedly succeeded") }
            catch (e: StegException) { check(e.message.orEmpty().contains(fragment)) { e.message.orEmpty() } }
        }
        try {
            test("ZIP creation rejects insufficient private space before any output or source read") {
                val before = work.listFiles()!!.toSet(); var read = false
                rejects {
                    MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                        Control(progress = { stage, _, _ -> if (stage == "打包文件") read = true }),
                        BundleDiskPolicy { reserve - 1 })
                }
                check(!read && work.listFiles()!!.toSet() == before)
            }
            val planned = MultiFileBundle.plannedArchiveBytes(source.length(), sources.size, LIMIT)
            test("ZIP space estimate is bounded and cannot overflow") {
                check(planned >= source.length() && planned <= LIMIT)
                check(MultiFileBundle.plannedArchiveBytes(Long.MAX_VALUE, 100, LIMIT) == LIMIT)
                check(MultiFileBundle.plannedArchiveBytes(0, 1, LIMIT) > 0)
                check(MultiFileBundle.plannedArchiveBytes(source.length(), 1, 17) == 17L)
            }
            test("ZIP admission rejects one byte below planned workspace plus reserve") {
                val before = work.listFiles()!!.toSet()
                rejects { MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                    diskPolicy = BundleDiskPolicy { reserve + planned - 1 }) }
                check(work.listFiles()!!.toSet() == before)
            }
            test("ZIP creation succeeds at conservative bound while available space decreases") {
                val before = work.listFiles()!!.toSet(); var observed = 0
                val policy = BundleDiskPolicy {
                    observed++
                    reserve + planned - (work.listFiles()!!.toSet() - before).sumOf { it.length() }
                }
                val packed = MultiFileBundle.create(sources, work, LIMIT, LIMIT, diskPolicy = policy)
                check(packed.file.length() <= planned && observed > 2)
                println("ZIP disk-space observations: $observed for ${packed.file.length()} saved bytes")
                check(packed.info.entries.single().sha256 == original)
                check(packed.file.delete())
            }
            test("ZIP space checks are bounded by physical write chunks rather than deflater fragments") {
                var observations = 0
                val packed = MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                    diskPolicy = BundleDiskPolicy { observations++; Long.MAX_VALUE })
                try {
                    val bytes = packed.file.length()
                    val chunkChecks = (bytes + 65535) / 65536
                    println("Physical ZIP guard checks: $observations for $bytes bytes; 64 KiB chunks=$chunkChecks")
                    check(observations <= 10 + 2 * chunkChecks) { "Private free-space calls followed 512-byte deflater fragments: $observations" }
                } finally { check(packed.file.delete()) }
            }
            test("buffered ZIP output honors the exact archive byte limit and cleans a failed final flush") {
                val baseline = MultiFileBundle.create(sources, work, LIMIT, LIMIT)
                val exactBytes = baseline.file.length(); check(baseline.file.delete())
                val exact = MultiFileBundle.create(sources, work, LIMIT, exactBytes)
                check(exact.file.length() == exactBytes && exact.info.entries.single().sha256 == original)
                check(exact.file.delete())
                val before = work.listFiles()!!.toSet()
                rejects("容器") { MultiFileBundle.create(sources, work, LIMIT, exactBytes - 1) }
                check(work.listFiles()!!.toSet() == before)
            }
            test("cancellation during buffered ZIP creation removes its pending private output") {
                val before = work.listFiles()!!.toSet(); var cancel = false
                rejects("取消") {
                    MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ -> if (stage == "打包文件" && count > 0) cancel = true },
                            cancelled = { cancel }))
                }
                check(cancel && work.listFiles()!!.toSet() == before && sha256(source.readBytes()) == original)
            }
            test("space lost during compression removes only the owned partial ZIP") {
                val before = work.listFiles()!!.toSet(); var available = reserve + planned; var changed = false
                rejects {
                    MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ ->
                            if (stage == "打包文件" && count > 0) { available = reserve + 1; changed = true }
                        }), BundleDiskPolicy { available })
                }
                check(changed && work.listFiles()!!.toSet() == before)
            }
            val packed = MultiFileBundle.create(sources, work, LIMIT, LIMIT)
            val entry = packed.info.entries.single()
            test("selected extraction rejects insufficient exact member space before creating a temporary file") {
                val before = work.listFiles()!!.toSet(); var extracted = false
                rejects {
                    MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT,
                        Control(progress = { stage, _, _ -> if (stage == "提取文件") extracted = true }),
                        BundleDiskPolicy { reserve + entry.size - 1 })
                }
                check(!extracted && work.listFiles()!!.toSet() == before)
            }
            test("selected extraction succeeds with exactly member size plus reserve") {
                val before = work.listFiles()!!.toSet(); var observed = 0
                val restored = MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT,
                    diskPolicy = BundleDiskPolicy {
                        observed++; reserve + entry.size - (work.listFiles()!!.toSet() - before).sumOf { it.length() }
                    })
                check(observed > 2 && sha256(restored.readBytes()) == original)
                check(restored.delete())
            }
            test("space lost during extraction removes its partial member but preserves the authenticated ZIP") {
                val before = work.listFiles()!!.toSet(); var available = reserve + entry.size; var changed = false
                rejects {
                    MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ ->
                            if (stage == "提取文件" && count > 0) { available = reserve; changed = true }
                        }), BundleDiskPolicy { available })
                }
                check(changed && work.listFiles()!!.toSet() == before)
            }
            test("ENOSPC failures during a private write are explicitly mapped and cleaned") {
                val before = work.listFiles()!!.toSet()
                rejects {
                    MultiFileBundle.create(sources, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ -> if (stage == "打包文件" && count > 0)
                            throw IOException("write failed: ENOSPC (No space left on device)") }))
                }
                rejects {
                    MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ -> if (stage == "提取文件" && count > 0)
                            throw IOException("write failed", IOException("ENOSPC")) }))
                }
                check(work.listFiles()!!.toSet() == before)
            }
            test("space error mapping preserves the cause and distinguishes unrelated IO errors") {
                for (error in listOf(IOException("ENOSPC"), IOException("No space left on device"),
                    FileSystemException("synthetic", null, "There is not enough space on the disk"))) {
                    val mapped = BundleDiskPolicy().mapFailure(error)
                    check(mapped.message.orEmpty().contains("空间不足") && mapped.cause === error)
                }
                check(!BundleDiskPolicy().mapFailure(IOException("permission denied")).message.orEmpty().contains("空间不足"))
            }
            test("structured filesystem reasons ignore ENOSPC in a source path") {
                val error = FileSystemException("synthetic-ENOSPC.txt", null, "Permission denied")
                val mapped = BundleDiskPolicy().mapFailure(error)
                check(mapped.cause === error && !mapped.message.orEmpty().contains("空间不足"))
            }
            test("cancellation still cleans its own private output without deleting source or ZIP") {
                val before = work.listFiles()!!.toSet(); var cancel = false
                rejects("取消") {
                    MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT,
                        Control(progress = { stage, count, _ -> if (stage == "提取文件" && count > 0) cancel = true },
                            cancelled = { cancel }))
                }
                check(work.listFiles()!!.toSet() == before && sha256(source.readBytes()) == original)
            }
            println("Private bundle disk regressions: $passed passed")
        } finally {
            check(work.canonicalPath.startsWith(root.canonicalPath + File.separator))
            work.listFiles().orEmpty().forEach { check(it.isFile && it.delete()) }
            check(work.delete())
        }
    }
}
