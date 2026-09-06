package com.moyle.steg.android

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import java.util.Locale

/** The values shown here are observations and limits, never an allocation or heap override. */
@Composable
internal fun ResourcesPanel(state:UiState,vm:MoyleViewModel){
    var expanded by rememberSaveable { mutableStateOf(false) }
    val colors=MaterialTheme.colorScheme
    val enabled=!state.busy && !state.selecting
    val snapshot=state.memorySnapshot
    val plan=state.memoryPlan
    val maximum=snapshot?.let(MemoryPolicy::maximumManualMiB)
    Card(modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(18.dp),
        border=BorderStroke(1.dp,colors.outline.copy(alpha=0.6f)),
        colors=CardDefaults.cardColors(containerColor=colors.surface)){
        Column(Modifier.padding(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
            TextButton(onClick={expanded=!expanded;if(expanded && enabled)vm.refreshResources()},
                modifier=Modifier.fillMaxWidth().heightIn(min=48.dp),contentPadding=PaddingValues(0.dp)){
                Text("高级资源设置",modifier=Modifier.weight(1f),style=MaterialTheme.typography.titleMedium)
                Text(if(expanded)"收起 ▴"else "展开 ▾",style=MaterialTheme.typography.labelMedium)
            }
            Text(buildString {
                append(if(state.manualMemory)"手动预算"else "自动评估")
                if(plan!=null)append(" · ${MemoryPolicy.mib(plan.budgetBytes)} MiB")
                if(state.manualMemory && !state.resourceAcknowledged)append(" · 本次尚未确认")
            },style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
            state.resourceError?.let {Text(it,style=MaterialTheme.typography.bodySmall,color=colors.error)}
            if(expanded){
                Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                    FilterChip(selected=!state.manualMemory,onClick={vm.manualMemory(false)},enabled=enabled,label={Text("自动评估")})
                    FilterChip(selected=state.manualMemory,onClick={vm.manualMemory(true)},enabled=enabled,label={Text("手动设置")})
                }
                if(snapshot!=null){
                    ResourceLine("应用堆上限",MemoryPolicy.mib(snapshot.heapLimitBytes)+" MiB")
                    ResourceLine("应用堆当前可用",MemoryPolicy.mib(snapshot.heapAvailableBytes)+" MiB")
                    ResourceLine("系统当前可用",snapshot.systemAvailableBytes?.let{resourceSize(it)} ?: "系统未提供")
                    ResourceLine("本次工作预算",plan?.let{MemoryPolicy.mib(it.budgetBytes)+" MiB"} ?: "尚未确定")
                    if(snapshot.lowMemory)Text("系统正在报告低内存状态，请先关闭其他任务。",color=colors.error,style=MaterialTheme.typography.bodySmall)
                }else Text("尚未取得资源信息。可点下方按钮检测，开始任务前也会重新检查。",style=MaterialTheme.typography.bodySmall)
                Text(when {
                    maximum==null->"手动范围将在资源检测后显示。"
                    maximum<32->"当前没有满足安全余量的手动预算范围。"
                    else->"当前可手动设置：32～$maximum MiB。"
                },style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
                if(state.manualMemory){
                    OutlinedTextField(value=state.manualMemoryMiB,onValueChange=vm::manualMemoryMiB,
                        label={Text("工作内存预算（MiB）")},singleLine=true,enabled=enabled,
                        isError=state.resourceError!=null,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),
                        modifier=Modifier.fillMaxWidth())
                    Row(verticalAlignment=Alignment.Top){
                        Checkbox(checked=state.resourceAcknowledged,onCheckedChange=vm::acknowledgeResources,enabled=enabled,
                            modifier=Modifier.semantics{contentDescription="确认本次手动内存预算"})
                        Text("我确认本次手动预算。它不预留内存，也不会突破 Android 的应用堆限制。任务结束或设置改变后需重新确认。",
                            modifier=Modifier.weight(1f).padding(top=10.dp),style=MaterialTheme.typography.bodySmall)
                    }
                }
                OutlinedButton(onClick=vm::refreshResources,enabled=enabled,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)){
                    Text("重新检测当前资源")
                }
                Text("数值会随其他任务变化，开始处理时重新读取。PNG／GIF 仍需图片缓冲；独立 SAES 使用固定大小缓冲处理最高 1 GiB 原文件。口令派生仍需要固定工作内存，磁盘空间另行检查。",
                    style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
            }
        }
    }
}

@Composable private fun ResourceLine(label:String,value:String){
    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(10.dp)){
        Text(label,modifier=Modifier.weight(1f),style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value,style=MaterialTheme.typography.bodySmall)
    }
}

internal fun resourceSize(bytes:Long):String=when {
    bytes>=1024L*1024*1024->String.format(Locale.ROOT,"%.2f GiB",bytes.toDouble()/(1024L*1024*1024))
    bytes>=1024L*1024->String.format(Locale.ROOT,"%.1f MiB",bytes.toDouble()/(1024L*1024))
    bytes>=1024->String.format(Locale.ROOT,"%.1f KiB",bytes.toDouble()/1024)
    else->"$bytes B"
}

@Composable
internal fun DocumentProbeLabel(probe:DocumentProbe){
    val colors=MaterialTheme.colorScheme
    val format=when(probe.format){"png"->"PNG";"gif"->"GIF";"saes"->"SAES";else->"普通文件／未识别容器"}
    Column(verticalArrangement=Arrangement.spacedBy(4.dp)){
        Text("按文件内容识别：$format",style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
        if(probe.width!=null && probe.height!=null)
            Text("文件头尺寸：${probe.width} × ${probe.height} px",style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
        Text("报告大小：${probe.size?.let(::resourceSize) ?: "提供方未报告"}",style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
        Text("仅为文件头信息，尚未完成格式验证或认证；不依据后缀、相册缩略图判断。",style=MaterialTheme.typography.bodySmall,color=colors.onSurfaceVariant)
    }
}
