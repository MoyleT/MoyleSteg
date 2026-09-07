# Android 0.4.1-alpha · 多文件可靠性修复验证

日期：2026-09-07。仅使用合成内容、文件名和公开测试凭据。
Windows 主机，JDK21、Gradle8.13、Robolectric4.16；项目、构建、SDK、缓存和临时数据位于 H 盘。

| 实际检查 | 结果 |
|---|---|
| app 主机测试 | 196 项通过，0 失败、错误或跳过 |
| 文档临时空间 | 6 项主机回归 |
| 提供方选择取消 | 11 项主机回归 |
| 导航成果保护 | 8 项主机回归 |
| 多文件 ViewModel | 22 项主机回归 |
| Kotlin core:check | 通过，包含私有磁盘 15 项、受管 ZIP 20 项及既有协议回归 |
| ZIP 受限堆 | 64 MiB 合成成员，在 32 MiB JVM 最大堆中创建、检查并恢复 |
| 跨端容器 | 12 组 PNG／GIF／SAES、口令／密钥双向核验；60 次成员恢复核对 |
| 旧参考实现回退 | 6 组恢复完整 ZIP，30 次成员核对 |
| APK／测试 APK | 构建通过；versionCode 9；普通 APK 与 0.4.0 同一调试签名 |
| lint | 0 错误，9 条警告；类别见机器汇总 |
| 原有加密核心 | 13 个既有生产文件与 0.3.2、0.4.0 源码包逐字节相同；本轮核心改动限于 MultiFileBundle.kt |
| 普通 APK | 检查未带入合成测试资源或测试密钥 assets |

各测试类已经计入 app 总数，不应重复相加。APK 大小、SHA-256、签名摘要、逐类统计与最后 12 个容器摘要见[机器汇总](0.4.1-alpha/validation.json)。
双向容器及旧参考实现的逐项证据见[跨端结果](0.4.1-alpha/cross-end-envelope-summary.json)和[参考验证](0.4.1-alpha/reference-envelope-verification.json)。

## 这次确认的行为

私有临时空间按捕获、ZIP、后续封装与成员恢复阶段检查，保留 32 MiB 余量。
ZIP 独立回读验证完成后释放源捕获副本，再继续加密。磁盘预算采用保守估算，既不预留磁盘，也不保证其他应用不会随后占用空间。
空间边界、途中可用空间下降和 ENOSPC 采用受控注入；没有把手机实际写满。

文件选择任务有独立取消与版本标识，提供方 query/open 接入支持取消的接口，读取有检查点并尝试关闭句柄。
过时回复不能覆盖新选择；不保证忽略取消或阻塞在外部调用的提供方立即退出。

设置往返保留当前功能、草稿和结果，重复点击当前页不重置。切换真实功能或清空尚未保存成果时先确认丢弃，取消确认继续保留。
确认绑定当时结果；已保存到 Download／SAF 的公开文件不会因为导航、重试、取消或私有清理而删除。
具体规则见[修复说明](../docs/RELIABILITY_0_4_1.md)。

## 验证范围

Robolectric 使用合成 ContentProvider／MediaStore，执行产品代码及实际临时文件读写。
这些是主机回归，不等于手机系统提供方、原生权限弹窗或 Compose 渲染的实测。
设备测试 APK 已编译，新增设置、生成密钥、当前页与丢弃确认的 Compose 场景，但本轮未在手机或模拟器执行。
未执行 iQOO 13 真机验收、真实磁盘耗尽或设备性能测试；[设备清单](../docs/DEVICE_ACCEPTANCE.md)中相应项目保持待执行。

此 APK 供用户验收，使用调试签名；0.4.0 报告保留为历史记录，其测试数字不代替本轮结果。
PNG／GIF／SAES 外层 v1 协议未改变，三主题与默认 Download 恢复流程继续保留。

## 重跑

```text
./gradlew :core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
python tools/package_source.py
```

Windows 使用 gradlew.bat。公开源包用明确白名单和逐文件 SHA-256 清单，排除私人诊断目录、缓存和签名私钥。
