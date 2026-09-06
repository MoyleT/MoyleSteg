package com.moyle.steg.core

/** Conservative admission estimates, not a heap reservation or an exact JVM peak. */
internal object MemoryChecks {
    const val BUFFER_OVERHEAD = 64L * 1024
    private const val HEAP_RESERVE = 16L * 1024 * 1024

    fun requireWorking(bytes: Long,limits: Limits,stage: String) {
        demand(bytes>=0 && bytes<=limits.maxPngWorkingBytes,
            "$stage 估计需要 $bytes 字节，超过内存预算 ${limits.maxPngWorkingBytes} 字节。请提高可用预算或换用内存充足的设备恢复原文件。")
    }

    fun checkAdditional(bytes: Long,stage: String) {
        val runtime=Runtime.getRuntime()
        val used=runtime.totalMemory()-runtime.freeMemory()
        val available=maxOf(0L,runtime.maxMemory()-used-HEAP_RESERVE)
        // Other threads can allocate after this observation; do not force a GC or claim a reservation.
        demand(bytes>=0 && bytes<=available,
            "$stage 预计还需 $bytes 字节，超过当前可用堆预算 $available 字节（已留出 16 MiB）。请减少同时运行的任务或换用内存充足的设备。")
    }

    fun admit(resident: Long,additional: Long,limits: Limits,stage: String) {
        demand(resident>=0 && additional>=0 && resident<=Long.MAX_VALUE-additional,"内存估计超过有效预算范围。")
        requireWorking(resident+additional,limits,stage)
        checkAdditional(additional,stage)
    }
}
