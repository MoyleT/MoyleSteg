package com.moyle.steg.core

/** Public synthetic vectors, independently calculated by desktop_1_4_1.py::_key_fingerprint. */
object FingerprintRegression {
    @JvmStatic fun main(args: Array<String>) {
        val vectors = listOf(
            ByteArray(32) to "cec2-1ee6-aeee-d997-91fd",
            ByteArray(32) { it.toByte() } to "9171-18e8-7608-9c8e-4bc5",
            ByteArray(32) { 255.toByte() } to "5d4f-0521-a58b-ddfb-cfc8"
        )
        for ((key, expected) in vectors) {
            val before = key.copyOf()
            check(Credential.fingerprint(key) == expected)
            check(key.contentEquals(before)) { "Fingerprint must not alter the key" }
        }
        for (size in listOf(0, 31, 33)) {
            var rejected = false
            try { Credential.fingerprint(ByteArray(size)) } catch (_: StegException) { rejected = true }
            check(rejected) { "Fingerprint accepted a $size-byte key" }
        }
        println("PASS 3 desktop fingerprint vectors, unchanged key bytes, and invalid key lengths")
    }
}
