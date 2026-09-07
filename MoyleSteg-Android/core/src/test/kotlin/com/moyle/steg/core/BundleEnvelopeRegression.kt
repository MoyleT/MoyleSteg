package com.moyle.steg.core

import java.io.File

/** Real v1 envelopes around the same public synthetic managed ZIP, in both credentials. */
object BundleEnvelopeRegression {
    private const val ZIP_SHA256 = "d8d275189277d1802b39fe80e7845303b684479f147e295fc2059a9ebefe0dc0"
    private const val PASSWORD = "synthetic-bundle-password"
    private const val BUDGET = 4L * 1024 * 1024

    @JvmStatic fun main(args: Array<String>) {
        val fixtures = File(args[0])
        val gifCover = File(args[1]).readBytes()
        val output = File(args[2]).apply { mkdirs() }
        val work = File(output, "private-${System.nanoTime()}").apply { mkdirs() }
        val zip = File(fixtures, "python-bundle.zip")
        val payload = zip.readBytes()
        check(sha256(payload) == ZIP_SHA256)
        val expected = MultiFileBundle.inspect(zip, BUDGET, BUDGET)!!
        check(expected.entries.size == 5 && expected.totalBytes == 4223L)
        val pixels = RgbaImage(160, 120, ByteArray(160 * 120 * 4) {
            if (it % 4 == 3) 255.toByte() else (it * 37 + it / 640).toByte()
        })
        val pngCover = PngCodec.encode(pixels)
        pixels.rgba.fill(0)
        val verifiedIncoming = ArrayList<String>()
        val generated = ArrayList<String>()
        var memberChecks = 0

        fun verifyRecovered(file: File, filename: String) {
            check(filename == MultiFileBundle.FILENAME)
            check(file.length() == payload.size.toLong() && sha256(file.readBytes()) == ZIP_SHA256)
            val info = MultiFileBundle.inspect(file, BUDGET, BUDGET)!!
            check(info == expected)
            for (entry in info.entries) {
                val member = MultiFileBundle.extract(file, entry, work, BUDGET, BUDGET)
                try {
                    check(member.length() == entry.size && sha256(member.readBytes()) == entry.sha256)
                    memberChecks++
                } finally { check(member.delete()) }
            }
        }

        fun verifyEnvelope(file: File, credential: Credential, format: String) {
            if (format == "saes") {
                val decoded = SaesFiles().decrypt(file, credential, work)
                try { verifyRecovered(decoded.output!!, decoded.filename) }
                finally { check(decoded.output!!.delete()) }
            } else {
                val decoded = StegEngine().decode(file.readBytes(), credential)
                val recovered = File.createTempFile("recovered-", ".zip", work)
                try {
                    recovered.writeBytes(decoded.data)
                    verifyRecovered(recovered, decoded.filename)
                } finally { decoded.data.fill(0); check(recovered.delete()) }
            }
        }

        fun row(name: String, bytes: ByteArray): String =
            """{"container":"$name","container_sha256":"${sha256(bytes)}","payload_sha256":"$ZIP_SHA256","members":5}"""

        try {
            for (mode in listOf("key", "password")) {
                val credential = if (mode == "key") Credential.key(ByteArray(32) { it.toByte() }) else Credential.password(PASSWORD)
                credential.use {
                    for (format in listOf("png", "gif", "saes")) {
                        val incoming = File(fixtures, "envelopes/python-$mode.$format")
                        verifyEnvelope(incoming, credential, format)
                        verifiedIncoming += row(incoming.name, incoming.readBytes())
                        println("PASS Python -> Kotlin managed ZIP: $mode/$format; complete ZIP and all 5 members verified")

                        val target = File(output, "kotlin-$mode.$format")
                        if (format == "saes") {
                            val encrypted = SaesFiles().encrypt(zip, MultiFileBundle.FILENAME, credential, work)
                            try { encrypted.output!!.copyTo(target, overwrite = true) }
                            finally { check(encrypted.output!!.delete()) }
                        } else {
                            val cover = if (format == "png") pngCover else gifCover
                            target.writeBytes(StegEngine().hide(cover, MultiFileBundle.FILENAME, payload, credential))
                        }
                        verifyEnvelope(target, credential, format)
                        generated += row(target.name, target.readBytes())
                        println("PASS Kotlin generated and self-verified managed ZIP: $mode/$format")
                    }
                }
            }
            File(output, "kotlin-envelope-verification.json").writeText("""{
                "synthetic_only":true,
                "payload_sha256":"$ZIP_SHA256",
                "python_to_kotlin":[${verifiedIncoming.joinToString(",")}],
                "kotlin_generated_self_verified":[${generated.joinToString(",")}],
                "member_extractions_checked":$memberChecks,
                "reverse_direction_verification":"recorded separately by Python consumer"
            }""".trimIndent())
            check(verifiedIncoming.size == 6 && generated.size == 6 && memberChecks == 60)
            println("Bundle envelope interoperability: 6 Python -> Kotlin verified, 6 Kotlin outputs self-verified, 60 member extractions checked")
        } finally {
            payload.fill(0); pngCover.fill(0); gifCover.fill(0)
            check(work.canonicalPath.startsWith(output.canonicalPath + File.separator))
            work.listFiles().orEmpty().forEach { check(it.isFile && it.delete()) }
            check(work.delete())
        }
    }
}
