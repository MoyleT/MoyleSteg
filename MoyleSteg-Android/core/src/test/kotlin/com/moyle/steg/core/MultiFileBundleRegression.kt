package com.moyle.steg.core

import java.io.File
import java.io.RandomAccessFile
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

object MultiFileBundleRegression {
    private const val LIMIT = 4L * 1024 * 1024
    private const val MARKER = "MOYLESTEG-BUNDLE-V1"
    @JvmStatic fun main(args: Array<String>) {
        val root = File(args[0]).apply { mkdirs() }
        if (args.getOrNull(1) == "lowheap") {
            lowHeap(root, args.getOrNull(2)?.toLong() ?: (64L * 1024 * 1024))
            return
        }
        val work = File(root, "work-${System.nanoTime()}").apply { mkdirs() }
        val first = File(root, "synthetic-a.txt").apply { writeText("合成文件 Strawberry\n") }
        val second = File(root, "synthetic-b.txt").apply { writeBytes(ByteArray(180000) { (it % 251).toByte() }) }
        val empty = File(root, "synthetic-empty").apply { writeBytes(byteArrayOf()) }
        val sources = listOf(BundleSource(first, "草莓.txt"), BundleSource(second, "草莓.txt"), BundleSource(empty, "empty.bin"))
        var passed = 0
        fun test(name: String, action: () -> Unit) { action(); passed++; println("PASS $name") }
        fun rejects(action: () -> Unit) { try { action(); error("Unexpected success") } catch (_: StegException) {} }
        try {
            test("ordinary zip is restored as one file") {
                val ordinary = File(root, "ordinary.zip")
                ZipOutputStream(ordinary.outputStream()).use { it.putNextEntry(ZipEntry("note.txt")); it.write(1); it.closeEntry() }
                check(MultiFileBundle.inspect(ordinary, LIMIT, LIMIT) == null)
            }
            test("ordinary ZIP comment ending with the marker is not the exact managed comment") {
                for (comment in listOf("ordinary ZIP note: $MARKER", "普通注释 $MARKER", "$MARKER ordinary")) {
                    val ordinary = File(root, "ordinary-comment.zip")
                    ZipOutputStream(ordinary.outputStream()).use {
                        it.setComment(comment); it.putNextEntry(ZipEntry("note.txt")); it.write(42); it.closeEntry()
                    }
                    check(MultiFileBundle.inspect(ordinary, LIMIT, LIMIT) == null)
                }
            }
            test("ordinary non-ZIP text ending with the marker stays a single file") {
                for (text in listOf(MARKER, "A normal README may mention this marker.\n$MARKER")) {
                    val ordinary = File(root, "ordinary-marker.txt").apply { writeText(text) }
                    check(MultiFileBundle.inspect(ordinary, LIMIT, LIMIT) == null)
                }
            }
            val packed = MultiFileBundle.create(sources, work, LIMIT, LIMIT)
            test("managed zip roundtrip keeps order duplicate names UTF8 and empty entries") {
                check(packed.info.entries.map { it.name } == sources.map { it.name })
                check(packed.info.entries.map { it.index } == listOf(1, 2, 3))
                check(packed.info.totalBytes == sources.sumOf { it.file.length() })
                check(MultiFileBundle.inspect(packed.file, LIMIT, LIMIT) == packed.info)
                packed.info.entries.forEachIndexed { index, entry ->
                    val out = MultiFileBundle.extract(packed.file, entry, work, LIMIT, LIMIT)
                    check(out.name != entry.name && out.readBytes().contentEquals(sources[index].file.readBytes()))
                    check(out.delete())
                }
                packed.file.copyTo(File(root, "kotlin-bundle.zip"), overwrite = true)
                File(root, "kotlin-expected.json").writeText("""{
                  "archive": "kotlin-bundle.zip",
                  "sha256": "${sha256(packed.file.readBytes())}",
                  "total_bytes": ${packed.info.totalBytes},
                  "entries": [${packed.info.entries.joinToString(",") {
                      """{"index":${it.index},"name":"${it.name}","size":${it.size},"sha256":"${it.sha256}"}"""
                  }}]
                }""".trimIndent())
            }
            test("count name and source budgets reject before any output") {
                val before = work.listFiles()!!.toSet()
                rejects { MultiFileBundle.create(emptyList(), work, LIMIT, LIMIT) }
                rejects { MultiFileBundle.create(List(101) { sources[0] }, work, LIMIT, LIMIT) }
                for (name in listOf("../x", "CON.txt", "C:relative.txt", "name:stream", "trailing.", "a".repeat(181))) {
                    rejects { MultiFileBundle.create(listOf(BundleSource(first, name)), work, LIMIT, LIMIT) }
                }
                rejects { MultiFileBundle.create(sources, work, 32, LIMIT) }
                check(work.listFiles()!!.toSet() == before)
            }
            test("archive and expanded budgets independently reject") {
                rejects { MultiFileBundle.inspect(packed.file, LIMIT, packed.file.length() - 1) }
                rejects { MultiFileBundle.inspect(packed.file, packed.info.totalBytes - 1, LIMIT) }
                rejects { MultiFileBundle.create(sources, work, LIMIT, 64) }
            }
            test("selection metadata cannot redirect or mislabel extraction") {
                val entry = packed.info.entries.first()
                for (wrong in listOf(entry.copy(index = 9), entry.copy(name = "other.txt"), entry.copy(size = entry.size + 1), entry.copy(sha256 = "0".repeat(64)))) {
                    val before = work.listFiles()!!.toSet()
                    rejects { MultiFileBundle.extract(packed.file, wrong, work, LIMIT, LIMIT) }
                    check(work.listFiles()!!.toSet() == before)
                }
            }
            test("creation cancellation cleans only owned partial output") {
                val before = work.listFiles()!!.toSet()
                rejects { MultiFileBundle.create(sources, work, LIMIT, LIMIT, Control(cancelled = { true })) }
                check(work.listFiles()!!.toSet() == before)
            }
            test("entry corruption is rejected without extracted files") {
                val corrupt = File(root, "corrupt.zip").apply { packed.file.copyTo(this, overwrite = true) }
                RandomAccessFile(corrupt, "rw").use { it.seek(50); val b = it.read(); it.seek(50); it.write(b xor 8) }
                rejects { MultiFileBundle.inspect(corrupt, LIMIT, LIMIT) }
            }
            test("marked malformed footer does not silently become an ordinary zip") {
                val corrupt = File(root, "bad-footer.zip").apply { packed.file.copyTo(this, overwrite = true) }
                RandomAccessFile(corrupt, "rw").use { it.seek(it.length() - MARKER.length - 22); it.write(0) }
                rejects { MultiFileBundle.inspect(corrupt, LIMIT, LIMIT) }
            }
            test("creation detects same length source changes even with restored timestamp") {
                val original = first.readBytes(); val stamp = first.lastModified(); var changed = false
                val before = work.listFiles()!!.toSet()
                try {
                    rejects {
                        MultiFileBundle.create(sources, work, LIMIT, LIMIT, Control(progress = { stage, count, _ ->
                            if (!changed && stage == "打包文件" && count > 0) {
                                changed = true; first.writeBytes(ByteArray(original.size) { 42 }); first.setLastModified(stamp)
                            }
                        }))
                    }
                    check(changed && work.listFiles()!!.toSet() == before)
                } finally { first.writeBytes(original) }
            }
            test("creation independently verifies the saved archive before returning") {
                val before = work.listFiles()!!.toSet(); var corrupted = false
                rejects {
                    MultiFileBundle.create(sources, work, LIMIT, LIMIT, Control(progress = { stage, _, _ ->
                        if (!corrupted && stage == "回读多文件包") {
                            corrupted = true
                            val saved = (work.listFiles()!!.toSet() - before).single()
                            RandomAccessFile(saved, "rw").use { it.seek(50); val byte = it.read(); it.seek(50); it.write(byte xor 8) }
                        }
                    }))
                }
                check(corrupted && work.listFiles()!!.toSet() == before)
            }
            test("malformed EOCD fields are bounded and rejected") {
                for ((offset, value) in listOf(4 to 1, 8 to 101, 10 to 0, 12 to -1, 16 to -1, 20 to 0)) {
                    val bad = File(root, "footer-$offset.zip").apply { packed.file.copyTo(this, overwrite = true) }
                    RandomAccessFile(bad, "rw").use { it.seek(it.length() - MARKER.length - 22 + offset); it.write(value) }
                    rejects { MultiFileBundle.inspect(bad, LIMIT, LIMIT) }
                }
            }
            test("unsafe paths directory entries and sequential index gaps are refused") {
                for (path in listOf("../secret.txt", "0001/../x", "0001/CON.txt", "0002/note.txt", "0001/", "0001/a/b")) {
                    val bad = File(root, "bad-path.zip")
                    ZipOutputStream(bad.outputStream()).use {
                        it.setComment(MARKER); it.putNextEntry(ZipEntry(path)); it.write(42); it.closeEntry()
                    }
                    rejects { MultiFileBundle.inspect(bad, LIMIT, LIMIT) }
                }
            }
            test("unsupported encryption methods flags extras symlink and ZIP64 metadata are refused") {
                val raw = packed.file.readBytes()
                val eocd = raw.size - MARKER.length - 22
                val central = (0..3).sumOf { (raw[eocd + 16 + it].toInt() and 255) shl (8 * it) }
                for ((offset, value) in listOf(8 to 1, 10 to 12, 30 to 4, 32 to 1, 34 to 1, 24 to -1, 41 to 0xa0)) {
                    val bad = File(root, "central-$offset.zip")
                    bad.writeBytes(raw.copyOf().also { it[central + offset] = value.toByte() })
                    rejects { MultiFileBundle.inspect(bad, LIMIT, LIMIT) }
                }
            }
            test("local metadata must agree with the central record") {
                val raw = packed.file.readBytes()
                val eocd = raw.size - MARKER.length - 22
                val central = (0..3).sumOf { (raw[eocd + 16 + it].toInt() and 255) shl (8 * it) }
                for (offset in listOf(4, 10, 12, 14)) {
                    val altered = raw.copyOf()
                    if (offset == 4) altered[4] = 10
                    else if (offset == 14) raw.copyInto(altered, 14, central + 16, central + 20)
                    else altered[offset] = (altered[offset].toInt() xor 1).toByte()
                    val bad = File(root, "local-$offset.zip").apply { writeBytes(altered) }
                    rejects { MultiFileBundle.inspect(bad, LIMIT, LIMIT) }
                }
            }
            test("bounded inspection supports stored standard ZIP entries") {
                val stored = File(root, "stored.zip"); val bytes = first.readBytes()
                ZipOutputStream(stored.outputStream()).use { zip ->
                    zip.setComment(MARKER)
                    val e = ZipEntry("0001/plain.txt").apply {
                        method = ZipEntry.STORED; size = bytes.size.toLong(); compressedSize = size
                        crc = java.util.zip.CRC32().also { it.update(bytes) }.value
                    }
                    zip.putNextEntry(e); zip.write(bytes); zip.closeEntry()
                }
                check(MultiFileBundle.inspect(stored, LIMIT, LIMIT)!!.entries.single().sha256 == sha256(bytes))
            }
            test("180 byte member name does not become a long temporary filename") {
                val long = MultiFileBundle.create(listOf(BundleSource(first, "a".repeat(180))), work, LIMIT, LIMIT)
                val out = MultiFileBundle.extract(long.file, long.info.entries.single(), work, LIMIT, LIMIT)
                check(out.name.length < 80 && out.readBytes().contentEquals(first.readBytes())); out.delete(); long.file.delete()
            }
            test("inspection and extraction cancellation preserve bundle and remove partial file") {
                val before = work.listFiles()!!.toSet(); val hash = sha256(packed.file.readBytes())
                rejects { MultiFileBundle.inspect(packed.file, LIMIT, LIMIT, Control(cancelled = { true })) }
                var cancel = false
                rejects { MultiFileBundle.extract(packed.file, packed.info.entries[1], work, LIMIT, LIMIT,
                    Control(progress = { stage, count, _ -> if (stage == "提取文件" && count > 0) cancel = true }, cancelled = { cancel })) }
                check(work.listFiles()!!.toSet() == before && sha256(packed.file.readBytes()) == hash)
            }
            if (args.size > 1) test("Python generated bundle inspects and extracts every member in Kotlin") {
                val fixture = File(args[1])
                check(sha256(fixture.readBytes()) == "d8d275189277d1802b39fe80e7845303b684479f147e295fc2059a9ebefe0dc0")
                val expected = listOf(
                    BundleEntry(1, "duplicate.txt", 26, "bc3e0b9c61c9d30c329496b55cea71b27fee9083ec2057e441cf14767299e013"),
                    BundleEntry(2, "duplicate.txt", 55, "31bb901de253b826bb4dfe44d6be8cdc0bc5a5a67a50cfa97da1669cd640cb4e"),
                    BundleEntry(3, "草莓与樱桃.txt", 46, "8c33bc4cef2623427d3b7cd008f5bd19aae9ee4533e3d4d3f887b032cc66ffa1"),
                    BundleEntry(4, "empty.bin", 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
                    BundleEntry(5, "random.bin", 4096, "4fd00bc5b5340415087d23d57f6120dd6d8ece06ba121f5050cd41c0dbe98223")
                )
                val info = MultiFileBundle.inspect(fixture, LIMIT, LIMIT)!!
                check(info.entries == expected && info.totalBytes == 4223L && info.archiveBytes == fixture.length())
                for (entry in info.entries) {
                    val extracted = MultiFileBundle.extract(fixture, entry, work, LIMIT, LIMIT)
                    check(extracted.length() == entry.size && sha256(extracted.readBytes()) == entry.sha256)
                    check(extracted.delete())
                }
            }
            println("Multi-file bundle regressions: $passed passed")
        } finally {
            check(work.canonicalPath.startsWith(root.canonicalPath + File.separator))
            work.listFiles().orEmpty().forEach { check(it.isFile && it.delete()) }
            check(work.delete())
        }
    }

    private fun lowHeap(root: File, size: Long) {
        val work = File(root, "bounded-${System.nanoTime()}").apply { mkdirs() }
        try {
            val source = File(work, "synthetic-large.bin")
            RandomAccessFile(source, "rw").use { it.setLength(size) }
            val packed = MultiFileBundle.create(listOf(BundleSource(source, "synthetic-large.bin")), work, size, size + 1048576)
            check(packed.info.totalBytes == size && packed.info.entries.single().size == size)
            val restored = MultiFileBundle.extract(packed.file, packed.info.entries.single(), work, size, size + 1048576)
            check(restored.length() == size)
            check(MultiFileBundle.inspect(packed.file, size, size + 1048576) == packed.info)
            println("PASS bounded bundle create/inspect/extract: $size original bytes; heap=${Runtime.getRuntime().maxMemory()}")
        } finally {
            check(work.canonicalPath.startsWith(root.canonicalPath + File.separator))
            work.listFiles().orEmpty().forEach { check(it.isFile && it.delete()) }
            check(work.delete())
        }
    }
}
