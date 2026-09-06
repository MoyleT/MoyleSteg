# Windows 1.5.1: smoother progress and easier retries

## 重试不再重复输入口令 / Credentials during retries

选路径失败、容量不足、普通任务失败和安全取消后，当前表单保留口令及确认口令；取消文件选择对话框也保留原路径。无需口令的容量预检和独立密钥生成不会清空其他页面。

成功完成隐藏、加密、提取、解密、验证或认证后查看信息时，只清理该任务使用页面的口令，并关闭明文显示。实际关闭窗口时清理所有页面；工作中关闭窗口仍先安全取消并等待线程结束。手动清空不会被重新填回。

这些值只留在当前窗口的输入控件中，未新增口令缓存，不保存到设置或日志。关闭或重新启动程序后需要重新输入。这项更改延长了失败后口令在活动窗口中的保留时间，便于修正参数后重试。

Failed paths, insufficient capacity, other job failures and cooperative cancellation preserve current password fields for retry. Cancelling a file chooser preserves its previous path. Capacity preflight and standalone key generation do not clear unrelated credentials. Successful authenticated operations clear only the page they used, including password visibility. Closing the window clears every page after any active worker finishes. Values remain in live form controls only, without another credential cache or settings/log persistence; manual clearing is respected.

## 界面响应 / Responsiveness

像素嵌入和提取包含大量 Python 计算。后台线程在核心已有的进度检查点短暂让出执行时间，使界面的 Python 绘制和事件处理能及时运行；原有进度信号限流、真实阶段计数和安全取消保持有效。

The worker yields for 1 ms at existing bounded progress checkpoints so Python GUI painting and event handlers can run during Python-heavy pixel work. The existing signal throttle, measured stage progress and cooperative cancellation remain. This is not a change to encryption, bit placement, PNG/SAES format v1 or GIF extension 001.

本次 Windows 原生 Qt 合成数据实测（单次本机测量，不是所有设备的性能保证）：

| 场景 / Scene | 32 ms 界面心跳最大间隔 / Maximum | P95 |
|---|---:|---:|
| 修改前，512 KiB 随机载荷 / Before | 169 ms | 137 ms |
| 正式修复，512 KiB / Fixed | 67 ms | 52 ms |
| 修改前，4 MiB，运行 10 秒后取消 / Before, cancelled | 233 ms | 171 ms |
| 正式修复，4 MiB，完整完成 / Fixed, complete | 86 ms | 51 ms |

512 KiB 案例使用 1400×1200 RGB 载体，4 MiB 案例使用 3600×3400 RGB 载体。正式修复的 4 MiB 隐写加落盘回读认证约 67.73 秒，说明界面更平稳不等于像素计算大幅加速。4 MiB 的修改前后测量时长不同，不应作为严格的全程速度对比。全部测量未观察到超过 500 ms 的心跳间隔，没有复现用户旧版 EXE 持续数秒“未响应”的现象。

The 512 KiB fixture uses a 1400×1200 RGB cover; the 4 MiB fixture uses 3600×3400. The fixed 4 MiB operation, including saved-file readback authentication, took about 67.73 seconds. Smoother interaction is not a claim of substantially faster pixel computation. The large before/after runs have different durations and are not a full-runtime speed comparison. No measured heartbeat gap exceeded 500 ms; this does not reproduce or establish a universal fix for multi-second Windows “Not responding” states. Synchronous image/crypto calls may still take time between cancellable checkpoints. The desktop payload pipeline remains memory-based.

## 发布验证 / Release validation

| 实际运行范围 / Run | 结果 / Result |
|---|---|
| Windows 完整源码测试（Qt offscreen） / Full source suite | 692 项通过，0 失败，0 跳过；JUnit 记录 382.25 秒 |
| Windows 源码原生自检 / Source native self-test | 65 项通过 |
| Windows 冻结 EXE 原生自检 / Frozen native self-test | 65 项通过 |
| 原生响应诊断 / Native responsiveness | 8 组合成实验，包含正式修复的 512 KiB 与 4 MiB 完整隐写、落盘回读认证 |

完整源码测试包含新增的 15 项口令重试测试，覆盖无效保存路径修正、容量不足后开启扩容、取消文件选择、预检、六类认证任务成功后只清使用页、关闭清理与不回填手动清空的字段。其他既有用例覆盖取消和正在运行时关闭。原生自检实际验证三主题、中英文、PNG/SAES/GIF 往返、取消后保留口令和关闭时全页清理；口令生命周期诊断仅记录布尔值。

The 15 new retry tests are included in the full-suite count. Source tests use Qt offscreen; source and frozen native checks run the Windows Qt backend against real controls. These are separate runs, not additive counts or an independent third-party audit. Only synthetic inputs are used. Local paths, raw logs and diagnostic screenshots remain outside the public archive. The responsiveness comparison uses the same production worker change before the release version marker was bumped; no Android changes are part of this Windows patch.

