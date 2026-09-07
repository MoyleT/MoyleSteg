package com.moyle.steg.android

import android.Manifest
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun MoyleApp(vm: MoyleViewModel) {
    val s by vm.state.collectAsStateWithLifecycle()
    val context=LocalContext.current
    var permissionToken by rememberSaveable { mutableStateOf<Long?>(null) }
    val storagePermission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){granted->
        permissionToken?.let{vm.onDownloadPermissionResult(it,granted)}
        permissionToken=null
    }
    LaunchedEffect(s.downloadPermissionRequest){
        s.downloadPermissionRequest?.let{token->
            permissionToken=token
            vm.consumeDownloadPermissionRequest(token)
            storagePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
    }
    var slot by rememberSaveable { mutableStateOf(DocSlot.INPUT.name) }
    val picker=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if(uri!=null)vm.pick(DocSlot.valueOf(slot),uri)
    }
    // Separate launchers preserve accurate MIME hints in document providers.
    val savePng=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("image/png")){uri->if(uri!=null)vm.export(uri)}
    val saveGif=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("image/gif")){uri->if(uri!=null)vm.export(uri)}
    val saveBinary=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")){uri->if(uri!=null)vm.export(uri)}
    fun select(next: DocSlot){slot=next.name;picker.launch(if(next==DocSlot.COVER)arrayOf("image/png","image/jpeg","image/gif")else arrayOf("*/*"))}
    BackHandler(s.busy){vm.requestCancel()}
    MoyleTheme(s.theme,s.largeText){
        val c=MaterialTheme.colorScheme
        Scaffold(containerColor=c.background,
            bottomBar={NavigationBar(containerColor=c.surface){
                listOf("隐藏","恢复","工具","设置").forEachIndexed { i,label ->
                    NavigationBarItem(selected=s.page==i,onClick={vm.page(i)},enabled=!s.busy,
                        icon={MoyleIcon(i)},label={Text(label)})
                }
            }}
        ){padding->
            Box(Modifier.fillMaxSize().padding(padding),contentAlignment=Alignment.TopCenter){
                LazyColumn(Modifier.widthIn(max=680.dp).fillMaxSize().imePadding(),
                    contentPadding=PaddingValues(horizontal=20.dp,vertical=20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
                    item {
                        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween){
                            Column{Text("MOYLE",style=MaterialTheme.typography.titleLarge,letterSpacing=3.sp);Text("隐写工坊 · Android",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)}
                            Surface(shape=RoundedCornerShape(50),color=c.primaryContainer){Text("本机处理",Modifier.padding(horizontal=12.dp,vertical=7.dp),style=MaterialTheme.typography.labelMedium)}
                        }
                    }
                    item {
                        Text(when(s.page){0->"把秘密藏进\n一张图片";1->"找回属于你的文件";2->"密钥与文件工具";else->"你的工坊"},style=MaterialTheme.typography.headlineLarge)
                        Spacer(Modifier.height(6.dp))
                        Text("0.3.2-alpha · 重要文件请保留独立备份。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                    }
                    if(s.page==3){
                        item{Section("外观"){
                            listOf("midnight" to "星夜 · 深邃蓝紫","blossom" to "樱桃奶霜 · 浅粉","terminal" to "终端 · 墨黑荧绿").forEach{(id,label)->
                                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){RadioButton(selected=s.theme==id,onClick={vm.theme(id)});TextButton(onClick={vm.theme(id)}){Text(label)}}
                            }
                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){Text("大字号");Switch(s.largeText,{vm.largeText(it)})}
                        }}
                        item{ResourcesPanel(s,vm)}
                        item{Section("当前能力与边界"){
                            Text("独立 SAES 加密、恢复与只读验证支持最高 1 GiB 原文件，使用固定大小缓冲；仍需足够临时磁盘和口令派生内存。")
                            Text("PNG／GIF 的秘密文件上限 32 MiB、完整容器上限 128 MiB、像素上限 1 亿，仍受本次内存预算约束。这些是处理上限，不保证所有手机都能处理到上限。",style=MaterialTheme.typography.bodySmall)
                            Text("支持非交错的 8 位 RGB／RGBA PNG，包括桌面 1.4.1 的标准输出。灰度、调色板、16 位、交错与动画 PNG 会被明确拒绝。",style=MaterialTheme.typography.bodySmall)
                            Text("JPG／JPEG 照片可作为新载体，按照片方向校正后输出 PNG；原 JPG 不变，成品不复制照片的 EXIF／GPS。",style=MaterialTheme.typography.bodySmall)
                            Text("GIF 保持原动画，使用标准扩展块装载密文，不是像素隐写。最多 500 帧、画布像素 × 帧数最多 1 亿，成品仍受容器及内存预算限制。GIF 互通需电脑版 1.5.0 或更新版。",style=MaterialTheme.typography.bodySmall)
                            Text("不要通过截图、裁剪、缩放或转换格式来修复隐写图。隐写并不保证不可检测。",style=MaterialTheme.typography.bodySmall)
                        }}
                        item{Section("隐私与退出"){
                            Text("应用不申请联网或全盘访问权限。恢复文件默认存入 Download：Android 10 及以上无需存储授权，Android 8／9 会申请保存权限。输入仍由系统选择器授权。")
                            Text("Download 中是已解密的文件，清空结果或卸载应用不会由本应用删除它们。点击“打开文件”后，所选应用会获得该文件的临时读取权限。云盘或查看应用可能自行联网处理文件。",style=MaterialTheme.typography.bodySmall)
                            Text("口令不保存到设置；离开应用时清空表单口令。私有临时成品在清空结果或下次进程启动时删除；保存失败可在当前结果直接重试。不承诺物理安全擦除。",style=MaterialTheme.typography.bodySmall)
                            Text("首版没有后台持续运行保证。请尽量保持前台，并单独备份密钥。",style=MaterialTheme.typography.bodySmall)
                        }}
                    }else{
                        if(s.page==1)item{Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                            FilterChip(selected=s.operation==Operation.RESTORE,onClick={vm.operation(Operation.RESTORE)},enabled=!s.busy,label={Text("恢复文件")})
                            FilterChip(selected=s.operation==Operation.VERIFY,onClick={vm.operation(Operation.VERIFY)},enabled=!s.busy,label={Text("只读验证")})
                        }}
                        if(s.page==2)item{Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                            FilterChip(selected=s.operation==Operation.ENCRYPT,onClick={vm.operation(Operation.ENCRYPT)},enabled=!s.busy,label={Text("独立 SAES 加密")})
                            FilterChip(selected=s.operation==Operation.KEYGEN,onClick={vm.operation(Operation.KEYGEN)},enabled=!s.busy,label={Text("生成密钥")})
                        }}
                        if(s.operation==Operation.KEYGEN){
                            item{ResourcesPanel(s,vm)}
                            item{Section("一把独立的 256-bit 密钥"){
                                Text("生成兼容电脑版的 .stegkey 文件。程序不会把它写进图片；没有密钥就无法恢复对应内容。")
                                Text("生成后先导出，再备份到与密文分开的位置。密钥文件本身没有口令加密。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                Button(onClick={vm.run()},enabled=!s.busy && !s.selecting,modifier=Modifier.fillMaxWidth().heightIn(min=52.dp)){Text("生成新密钥")}
                            }}
                        }else{
                            item{Section("01 / 选择文件"){
                                if(s.operation==Operation.HIDE)DocumentField("JPG／PNG／GIF 载体",s.cover,!s.busy,probe=s.coverProbe){select(DocSlot.COVER)}
                                DocumentField(if(s.operation in listOf(Operation.HIDE,Operation.ENCRYPT))"秘密文件"else "PNG／GIF／SAES 容器",s.input,!s.busy,probe=s.inputProbe){select(DocSlot.INPUT)}
                                if(s.operation==Operation.ENCRYPT)Text("独立 SAES 支持最高 1 GiB 原文件，不需要图片载体；成品保持电脑版兼容格式。接收端仍需允许相应的恢复预算。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                if(s.operation==Operation.HIDE){
                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically){
                                        Text("PNG 成品容量不足时自动扩容",modifier=Modifier.weight(1f))
                                        Switch(checked=s.autoExpand,onCheckedChange=vm::autoExpand,enabled=!s.busy)
                                    }
                                    Text("JPG／JPEG 照片输出为 PNG；先校正照片方向，再按需扩容和隐藏。容量足够时保持显示尺寸，原载体不变；超出预算可使用独立 SAES。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                    Text("GIF 保留原动画，无需扩容；密文扩展可被识别或在重编码时删除，请按文件发送。下方预检会自动识别格式。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                    OutlinedButton(onClick={vm.run(capacityOnly=true)},enabled=!s.busy && !s.selecting && s.input!=null && s.cover!=null,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)){Text("检查实际容量")}
                                    Text("先检查容量，再设置保护方式。预览或相册缩略图不会用作隐写输入。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                }
                            }}
                            item{ResourcesPanel(s,vm)}
                            item{Section("02 / 保护方式"){
                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){Text(if(s.useKey)"使用密钥文件"else "使用口令");Switch(s.useKey,{vm.useKey(it)},enabled=!s.busy)}
                                if(s.useKey)DocumentField(".stegkey 文件",s.key,!s.busy){select(DocSlot.KEY)}
                                else{
                                    OutlinedTextField(value=s.password,onValueChange=vm::setPassword,label={Text("口令")},singleLine=true,enabled=!s.busy,
                                        visualTransformation=PasswordVisualTransformation(),keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password,autoCorrectEnabled=false),modifier=Modifier.fillMaxWidth())
                                    if(s.operation==Operation.HIDE || s.operation==Operation.ENCRYPT)
                                        OutlinedTextField(value=s.confirmation,onValueChange=vm::setConfirmation,label={Text("再次输入口令")},singleLine=true,enabled=!s.busy,
                                            visualTransformation=PasswordVisualTransformation(),keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password,autoCorrectEnabled=false),modifier=Modifier.fillMaxWidth())
                                    Text("不要使用名字、生日或常见短语。口令不保存到磁盘。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                                }
                            }}
                            item{
                                Button(onClick={vm.run()},enabled=!s.busy && !s.selecting,modifier=Modifier.fillMaxWidth().heightIn(min=54.dp)){
                                    Text(when(s.operation){Operation.HIDE->"加密并隐藏文件";Operation.ENCRYPT->"加密为 SAES";Operation.VERIFY->"验证，不导出明文";else->"恢复到下载文件夹"})
                                }
                                Spacer(Modifier.height(8.dp))
                                Text(when(s.operation){
                                    Operation.RESTORE->"认证成功后自动保存到 Download，同名文件另取名称。完成后可直接选择应用打开。"
                                    Operation.VERIFY->"仅验证本次读取的数据，不会向下载文件夹写出恢复文件。"
                                    else->"处理通过后，再由你选择保存位置。不会自动覆盖原文件。"
                                },style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                            }
                        }
                    }
                    if(s.selecting)item{Section("正在读取文件信息"){
                        LinearProgressIndicator(modifier=Modifier.fillMaxWidth())
                        Text("文件信息确认后才可开始。你也可以重新选择或取消此次选择。",style=MaterialTheme.typography.bodySmall)
                        TextButton(onClick=vm::cancelSelection){Text("取消选择")}
                    }}
                    if(s.busy)item{Section("正在处理"){
                        Text(s.stage)
                        if(s.total>0)LinearProgressIndicator(progress={s.completed.toFloat()/s.total},modifier=Modifier.fillMaxWidth())
                        else LinearProgressIndicator(modifier=Modifier.fillMaxWidth())
                        Text("请保持应用在前台；密码学调用可能需要完成后才能响应取消。",style=MaterialTheme.typography.bodySmall)
                        OutlinedButton(onClick=vm::requestCancel,modifier=Modifier.fillMaxWidth()){Text("安全取消")}
                    }}
                    s.error?.let{error->item{Surface(shape=RoundedCornerShape(16.dp),color=c.errorContainer){Text(error,Modifier.padding(16.dp),color=c.onErrorContainer)}}}
                    s.result?.let{r->item{
                        Section(r.title){
                            Text(r.download?.displayName ?: r.filename,style=MaterialTheme.typography.titleMedium)
                            Text(r.message,style=MaterialTheme.typography.bodyMedium)
                            Text("输入：${r.inputLabel}\n完成于：${r.at}",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                            if(r.download!=null)Text("已保存至：${r.download.displayPath}",style=MaterialTheme.typography.bodySmall)
                            else if(r.exportedUri!=null)Text("已保存至所选位置",style=MaterialTheme.typography.bodySmall)
                            if(r.restored && r.exportedUri!=null){
                                Button(onClick={
                                    val outcome=RestoredFileActions.open(context,r.exportedUri,r.mime)
                                    if(outcome is OpenOutcome.Unavailable)vm.reportOpenFailure(outcome.message)
                                },enabled=!s.busy,modifier=Modifier.fillMaxWidth().heightIn(min=54.dp)){Text("打开文件")}
                                Text("选择一个应用查看；如果系统提示没有可用应用，可安装支持此格式的应用后再打开，文件已经保存。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)
                            }else if(r.restored && r.staged!=null){
                                Button(onClick=vm::saveRestoredToDownloads,enabled=!s.busy,modifier=Modifier.fillMaxWidth().heightIn(min=54.dp)){
                                    Text(if(r.needsStoragePermission)"授权并保存到下载文件夹" else "重试保存到下载文件夹")
                                }
                            }
                            if(r.staged!=null){
                                val saveCopy={when(r.mime){"image/png"->savePng.launch(r.suggestedName);"image/gif"->saveGif.launch(r.suggestedName);else->saveBinary.launch(r.suggestedName)}}
                                if(r.restored)OutlinedButton(onClick=saveCopy,enabled=!s.busy && !s.selecting,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)){
                                    Text(if(r.exportedUri==null)"选择其他位置保存" else "另存一份")
                                }else Button(onClick=saveCopy,enabled=!s.busy && !s.selecting,modifier=Modifier.fillMaxWidth().heightIn(min=50.dp)){
                                    Text(if(r.exportedUri==null)"选择位置并保存"else "另存一份")
                                }
                            }
                            var detail by remember(r.at){mutableStateOf(false)}
                            TextButton(onClick={detail=!detail}){Text(if(detail)"收起技术信息"else "展开摘要与技术信息")}
                            if(detail)SelectionContainer{Column(verticalArrangement=Arrangement.spacedBy(10.dp)){
                                if(r.restored)Text("认证的原文件名：${r.filename}",style=MaterialTheme.typography.bodySmall)
                                if(r.contentHash.isNotEmpty())HashText("原文件 SHA-256",r.contentHash)
                                if(r.containerHash.isNotEmpty())HashText("完整容器／密钥文件 SHA-256",r.containerHash)
                                if(r.exportedUri!=null)Text("保存文件 URI：${r.exportedUri}",style=MaterialTheme.typography.bodySmall)
                                Text("AES-256-GCM · 格式 v1 · 对应本次捕获数据",style=MaterialTheme.typography.bodySmall)
                            }}
                            TextButton(onClick=vm::clearResult,enabled=!s.busy){Text(if(r.restored && r.exportedUri!=null)"清空结果（已保存文件保留）" else "清空结果与私有成品")}
                        }
                    }}
                    item{Spacer(Modifier.height(8.dp));Text("让私密文件，隐于像素之间。",style=MaterialTheme.typography.bodySmall,color=c.onSurfaceVariant)}
                }
            }
        }
    }
}

@Composable private fun Section(title: String,content: @Composable ColumnScope.()->Unit){
    Card(modifier=Modifier.fillMaxWidth(),colors=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.surface),
        border=BorderStroke(1.dp,MaterialTheme.colorScheme.outline.copy(alpha=0.6f)),shape=RoundedCornerShape(18.dp)){
        Column(Modifier.padding(18.dp),verticalArrangement=Arrangement.spacedBy(14.dp)){
            Text(title,style=MaterialTheme.typography.titleMedium,color=MaterialTheme.colorScheme.primary)
            content()
        }
    }
}
@Composable private fun DocumentField(label: String,doc: PickedDocument?,enabled: Boolean,probe:DocumentProbe?=null,onChoose: ()->Unit){
    Text(label,style=MaterialTheme.typography.labelLarge)
    OutlinedButton(onClick=onChoose,enabled=enabled,shape=RoundedCornerShape(12.dp),modifier=Modifier.fillMaxWidth().heightIn(min=58.dp),
        border=BorderStroke(1.dp,MaterialTheme.colorScheme.outline)){
        Column(Modifier.weight(1f)){
            Text(doc?.name ?: "从系统文件选择器打开",maxLines=2,overflow=TextOverflow.Ellipsis,style=MaterialTheme.typography.bodyMedium)
        }
        Text("选择",Modifier.padding(start=12.dp),style=MaterialTheme.typography.labelLarge)
    }
    if(probe!=null)DocumentProbeLabel(probe)
}
@Composable private fun HashText(title: String,value: String){
    Column {Text(title,style=MaterialTheme.typography.labelMedium);Text(value,style=MaterialTheme.typography.bodySmall.copy(fontFamily=FontFamily.Monospace))}
}
@Composable private fun MoyleIcon(kind: Int){
    val color=MaterialTheme.colorScheme.onSurface
    Canvas(Modifier.size(24.dp)){
        val w=size.width;val h=size.height;val stroke=Stroke(width=2.dp.toPx())
        when(kind){
            0->{drawRoundRect(color,Offset(w*.12f,h*.15f),androidx.compose.ui.geometry.Size(w*.76f,h*.68f),androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()),style=stroke)
                val p=Path().apply{moveTo(w*.2f,h*.7f);lineTo(w*.42f,h*.43f);lineTo(w*.61f,h*.64f);lineTo(w*.72f,h*.51f);lineTo(w*.86f,h*.7f)};drawPath(p,color,style=stroke)}
            1->{drawLine(color,Offset(w*.5f,h*.1f),Offset(w*.5f,h*.65f),strokeWidth=2.dp.toPx(),cap=StrokeCap.Round)
                val p=Path().apply{moveTo(w*.25f,h*.43f);lineTo(w*.5f,h*.68f);lineTo(w*.75f,h*.43f);moveTo(w*.15f,h*.74f);lineTo(w*.15f,h*.9f);lineTo(w*.85f,h*.9f);lineTo(w*.85f,h*.74f)};drawPath(p,color,style=stroke)}
            2->{drawCircle(color,w*.21f,Offset(w*.3f,h*.3f),style=stroke);drawLine(color,Offset(w*.46f,h*.46f),Offset(w*.87f,h*.87f),strokeWidth=2.dp.toPx());drawLine(color,Offset(w*.7f,h*.7f),Offset(w*.85f,h*.55f),strokeWidth=2.dp.toPx())}
            else->{for(i in 0..2){val y=h*(.22f+i*.28f);drawLine(color,Offset(w*.12f,y),Offset(w*.88f,y),strokeWidth=2.dp.toPx());drawCircle(color,w*.075f,Offset(w*(if(i%2==0).35f else .68f),y))}}
        }
    }
}
