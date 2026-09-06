package com.moyle.steg.android

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

enum class Operation(val title: String) {
    HIDE("隐藏文件"), RESTORE("恢复文件"), VERIFY("验证文件"), ENCRYPT("独立加密"), KEYGEN("生成密钥")
}
enum class DocSlot { INPUT, COVER, KEY }
data class JobResult(
    val title: String,val inputLabel: String,val filename: String,val message: String,
    val contentHash: String="",val containerHash: String="",val at: String=now(),
    val staged: File?=null,val suggestedName: String="result.bin",val mime: String="application/octet-stream",
    val protectedUris: List<Uri> = emptyList(),val outputHash: String="",val exportedUri: Uri?=null,
    val preflight: Preflight?=null
)
fun now(): String = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
data class UiState(
    val page: Int=0,val operation: Operation=Operation.HIDE,
    val input: PickedDocument?=null,val cover: PickedDocument?=null,val key: PickedDocument?=null,
    val useKey: Boolean=false,val password: String="",val confirmation: String="",val autoExpand: Boolean=true,
    val theme: String="midnight",val largeText: Boolean=false,
    val manualMemory:Boolean=false,val manualMemoryMiB:String="128",val resourceAcknowledged:Boolean=false,
    val memorySnapshot:MemorySnapshot?=null,val memoryPlan:MemoryPlan?=null,val resourceError:String?=null,
    val inputProbe:DocumentProbe?=null,val coverProbe:DocumentProbe?=null,
    val busy: Boolean=false,val selecting: Boolean=false,val stage: String="",val completed: Int=0,val total: Int=0,
    val error: String?=null,val result: JobResult?=null
)

class MoyleViewModel @JvmOverloads constructor(application: Application,
    private val memoryReader:()->MemorySnapshot={DeviceResources.snapshot(application)}): AndroidViewModel(application) {
    private val docs=DocumentStore(application)
    private val prefs=application.getSharedPreferences("appearance",0)
    private val _state=MutableStateFlow(UiState(theme=prefs.getString("theme","midnight") ?: "midnight",largeText=prefs.getBoolean("large",false)))
    val state: StateFlow<UiState> = _state.asStateFlow()
    private val cancel=AtomicBoolean(false)
    private var job: Job?=null
    init { refreshResources() }
    fun refreshResources(){
        if(_state.value.busy)return
        val observed=memoryReader();val s=_state.value
        val planned=runCatching{MemoryPolicy.choose(observed,s.manualMemory,s.manualMemoryMiB.toIntOrNull() ?: 0)}
        _state.update{it.copy(memorySnapshot=observed,memoryPlan=planned.getOrNull(),resourceError=planned.exceptionOrNull()?.message)}
    }
    fun manualMemory(value:Boolean){if(!_state.value.busy){clearResult();_state.update{it.copy(manualMemory=value,resourceAcknowledged=false)};refreshResources()}}
    fun manualMemoryMiB(value:String){if(!_state.value.busy){clearResult();_state.update{it.copy(manualMemoryMiB=value.filter(Char::isDigit).take(4),resourceAcknowledged=false)};refreshResources()}}
    fun acknowledgeResources(value:Boolean){if(!_state.value.busy)_state.update{it.copy(resourceAcknowledged=value)}}
    // Accessed on the main thread. Each slot owns its latest metadata request.
    private var selectionSequence=0L
    private val selections=mutableMapOf<DocSlot,Long>()
    private fun invalidateSelections() {
        selections.clear()
        _state.update { it.copy(selecting=false,resourceAcknowledged=false) }
    }
    fun cancelSelection(){if(!_state.value.busy)invalidateSelections()}
    fun page(value: Int) {
        if(_state.value.busy)return
        invalidateSelections()
        clearResult()
        _state.update { it.copy(page=value,operation=when(value){0->Operation.HIDE;1->Operation.RESTORE;2->Operation.ENCRYPT;else->it.operation},password="",confirmation="",error=null) }
    }
    fun operation(value: Operation) {
        if(_state.value.busy)return
        invalidateSelections()
        clearResult();_state.update{it.copy(operation=value,password="",confirmation="",error=null)}
    }
    fun setPassword(value: String){if(!_state.value.busy)_state.update{it.copy(password=value.take(2048))}}
    fun setConfirmation(value: String){if(!_state.value.busy)_state.update{it.copy(confirmation=value.take(2048))}}
    fun useKey(value: Boolean){if(!_state.value.busy){invalidateSelections();clearResult();_state.update{it.copy(useKey=value,password="",confirmation="")}}}
    fun autoExpand(value: Boolean){if(!_state.value.busy){clearResult();_state.update{it.copy(autoExpand=value)}}}
    fun theme(value: String){prefs.edit().putString("theme",value).apply();_state.update{it.copy(theme=value)}}
    fun largeText(value: Boolean){prefs.edit().putBoolean("large",value).apply();_state.update{it.copy(largeText=value)}}
    fun clearPasswords(){_state.update{it.copy(password="",confirmation="")}}
    fun clearResult(){if(!_state.value.busy){_state.value.result?.staged?.delete();_state.update{it.copy(result=null,error=null)}}}
    fun requestCancel(){cancel.set(true);_state.update{it.copy(stage="正在等待安全取消点…")}}
    fun pick(slot: DocSlot,uri: Uri){
        if(_state.value.busy)return
        clearResult()
        val revision=++selectionSequence
        selections[slot]=revision
        // Remove the previous input immediately; it cannot stand in for a pending selection.
        _state.update { state ->
            val next=when(slot){DocSlot.INPUT->state.copy(input=null,inputProbe=null);DocSlot.COVER->state.copy(cover=null,coverProbe=null);DocSlot.KEY->state.copy(key=null)}
            next.copy(selecting=true,error=null,resourceAcknowledged=false)
        }
        viewModelScope.launch {
            try{
                val (doc,probe)=withContext(Dispatchers.IO){
                    val described=docs.describe(uri)
                    // A provider may supply metadata but not a preview stream. Actual jobs must still open and validate it.
                    val probe=if(slot==DocSlot.KEY)null else try{docs.probe(described,Control())}catch(_:Exception){null}
                    described to probe
                }
                if(selections[slot]==revision && !_state.value.busy){
                    clearResult()
                    _state.update { when(slot){DocSlot.INPUT->it.copy(input=doc,inputProbe=probe);DocSlot.COVER->it.copy(cover=doc,coverProbe=probe);DocSlot.KEY->it.copy(key=doc)} }
                }
            }catch(e: CancellationException){throw e}
            catch(_: Exception){if(selections[slot]==revision)_state.update{it.copy(error="无法读取选择的文件，请重新选择。")}}
            finally{
                if(selections[slot]==revision){
                    selections.remove(slot)
                    _state.update{it.copy(selecting=selections.isNotEmpty())}
                }
            }
        }
    }
    private fun control(context: kotlin.coroutines.CoroutineContext): Control {
        var last=0L;var lastStage=""
        return Control({ stage,done,total ->
            val t=System.nanoTime()
            if(stage!=lastStage || t-last>80_000_000 || (total>0 && done==total)){
                last=t;lastStage=stage;_state.update{it.copy(stage=stage,completed=done,total=total)}
            }
        },{cancel.get() || !context.isActive})
    }
    fun run(capacityOnly: Boolean=false){
        if(_state.value.busy || _state.value.selecting)return
        val s=_state.value
        if(s.manualMemory && !s.resourceAcknowledged){_state.update{it.copy(error="请在高级资源设置中确认本次手动预算。")};return}
        if(s.operation!=Operation.KEYGEN && s.input==null){_state.update{it.copy(error="请先选择输入文件。")};return}
        if(s.operation==Operation.HIDE && s.cover==null){_state.update{it.copy(error="请先选择 PNG／GIF 载体。")};return}
        if(!capacityOnly && s.operation!=Operation.KEYGEN){
            if(s.useKey && s.key==null){_state.update{it.copy(error="请选择 .stegkey 密钥文件。")};return}
            if(!s.useKey && (s.password.isEmpty() || ((s.operation==Operation.HIDE || s.operation==Operation.ENCRYPT) && s.password!=s.confirmation))){
                _state.update{it.copy(error="请输入口令；创建文件时两次输入必须一致。")};return
            }
        }
        clearResult();cancel.set(false)
        _state.update{it.copy(busy=true,error=null,result=null,stage="准备",password="",confirmation="",completed=0,total=0)}
        job=viewModelScope.launch {
            var staged: File?=null;var delivered=false
            try{
                val result=withContext(Dispatchers.IO){
                    val ctl=control(currentCoroutineContext())
                    process(s,capacityOnly,ctl){staged=it}
                }
                currentCoroutineContext().ensureActive()
                _state.update{it.copy(result=result,busy=false,stage="完成",password="",confirmation="")};delivered=true
            }catch(_: CancellationException){throw CancellationException()}
            catch(e: Exception){_state.update{it.copy(busy=false,error=if(e is StegException)e.message else "操作失败：请检查文件访问权限、存储空间及输入格式。",stage="未完成")}}
            finally{if(!delivered)staged?.delete();_state.update{it.copy(busy=false,password="",confirmation="",resourceAcknowledged=false)}}
        }
    }
    private fun process(s: UiState,capacityOnly: Boolean,ctl: Control,onStaged: (File)->Unit): JobResult {
        ctl.check()
        val observed=memoryReader()
        val plan=try{MemoryPolicy.choose(observed,s.manualMemory,s.manualMemoryMiB.toIntOrNull() ?: 0)}
            catch(e:StegException){_state.update{it.copy(memorySnapshot=observed,memoryPlan=null,resourceError=e.message)};throw e}
        _state.update{it.copy(memorySnapshot=observed,memoryPlan=plan,resourceError=null)}
        if(!capacityOnly && s.operation!=Operation.KEYGEN)MemoryPolicy.requireCredential(plan,s.useKey)
        val limits=MemoryPolicy.imageLimits(plan)
        val engine=StegEngine(limits,ctl)
        val protected=listOfNotNull(s.input?.uri,s.cover?.uri,s.key?.uri)
        fun stage(bytes: ByteArray): File=docs.stage(bytes,ctl).also(onStaged)
        if(s.operation==Operation.KEYGEN){
            ctl.report("生成系统随机密钥")
            val key=Credential.generateKey()
            try{
                val encoded=Credential.exportKey(key)
                try{
                    val file=stage(encoded)
                    val reread=file.readBytes()
                    try{Credential.keyFile(reread).close()}finally{reread.fill(0)}
                    return JobResult("密钥已生成","本机安全随机源","moyle.stegkey","指纹：${Credential.fingerprint(key)}\n请先导出并独立备份；未导出就清空或退出，密钥可能丢失。",
                        staged=file,suggestedName="moyle_${System.currentTimeMillis()}.stegkey",protectedUris=protected,containerHash=sha256(encoded),outputHash=sha256(encoded))
                }finally{encoded.fill(0)}
            }finally{key.fill(0)}
        }
        val doc=s.input ?: throw StegException("缺少输入文件。")
        val create=s.operation==Operation.HIDE || s.operation==Operation.ENCRYPT
        val probe=docs.probe(doc,ctl)
        if(s.operation==Operation.ENCRYPT || (!create && probe.format=="saes"))
            return processFile(s,doc,ctl,protected,onStaged)
        fun checkImage(p:DocumentProbe,payloadBytes:Long=0){
            if(p.size!=null && p.size>limits.maxContainerBytes)throw StegException("图片容器超过 128 MiB 预算；请勿缩放或重新保存原隐写图。")
            if(p.width!=null && p.height!=null && p.width.toLong()*p.height>limits.maxPixels)
                throw StegException("图片为 ${p.width} × ${p.height}，超过本次 ${limits.maxPixels} 像素预算；请勿缩放已有隐写图片。")
            MemoryPolicy.requireBytes(plan,MemoryPolicy.imageEstimate(p.size ?: 0,p.width ?: 0,p.height ?: 0,p.format,payloadBytes),"图片处理")
        }
        fun captureLimit(hard:Int,p:DocumentProbe?=null,payloadBytes:Long=0,copies:Int=4):Int {
            val fixed=MemoryPolicy.imageEstimate(0,p?.width ?: 0,p?.height ?: 0,p?.format ?: "file",payloadBytes)
            MemoryPolicy.requireBytes(plan,fixed+1,"图片读取")
            return minOf(hard.toLong(),(plan.budgetBytes-fixed)/copies).coerceAtLeast(1).toInt()
        }
        val coverInfo=if(s.operation==Operation.HIDE)docs.probe(s.cover ?: throw StegException("缺少载体。"),ctl)else null
        if(create){
            if(probe.size!=null && probe.size>limits.maxPayloadBytes)throw StegException("图片隐写的原文件上限为 32 MiB；大文件请使用工具页的独立 SAES 加密（最多 1 GiB）。")
            checkImage(coverInfo!!,probe.size ?: 0)
        }else checkImage(probe)
        // Unknown or stale provider sizes cannot bypass the buffer budget during capture itself.
        val input=docs.capture(doc,if(create)captureLimit(limits.maxPayloadBytes,copies=6)
            else captureLimit(limits.maxContainerBytes,probe),ctl)
        var cover: ByteArray?=null
        try{
            if(s.operation==Operation.HIDE){
                cover=docs.capture(s.cover ?: throw StegException("缺少载体。"),captureLimit(limits.maxContainerBytes,coverInfo,input.size.toLong()),ctl)
                checkImage(docs.probeBytes(cover),input.size.toLong())
            }else checkImage(docs.probeBytes(input))
            if(capacityOnly){
                val p=engine.preflight(cover ?: throw StegException("缺少载体。"),doc.name,input,autoExpand=s.autoExpand)
                if(p.format=="gif")return JobResult(if(p.fits)"GIF 预算检查通过"else "GIF 超出成品预算",doc.name,doc.name,
                    "GIF 动画：${p.frameCount} 帧 · ${p.width} × ${p.height}\n预计成品：${p.outputBytes} 字节\n原文件：${p.originalBytes} 字节\n压缩：${if(p.compressed)"是"else "否"}\n"+
                        "保留原动画，不改变尺寸。密文存储于标准扩展块，可被文件分析识别，重编码可能删除它；请按文件发送。\n"+
                        "预检不预留资源；执行时会重新读取并检查。",preflight=p)
                val occupancy=if(p.capacityBytes==0)"无可用容量" else String.format(Locale.ROOT,"%.1f%%",p.occupancyPercent)
                val memory=String.format(Locale.ROOT,"%.1f",p.estimatedWorkingBytes/1048576.0)
                return JobResult(when{!p.fits->"容量不足";p.expanded->"扩容后容量足够";else->"容量足够"},doc.name,doc.name,
                    "原载体：${p.originalWidth} × ${p.originalHeight}\n计划输出：${p.width} × ${p.height}\n需要扩容：${if(p.expanded)"是" else "否"}\n有效密文容量：${p.capacityBytes} 字节\n实际所需：${p.ciphertextBytes} 字节\n容量占用：$occupancy\n原文件：${p.originalBytes} 字节\n压缩：${if(p.compressed)"是" else "否"}\nPNG 工作内存估算：$memory MiB（未预留资源）\n"+
                        (if(!p.fits)"可开启自动扩容，或使用工具页的独立 SAES 加密。\n" else "")+
                        "预检不会生成成品；执行时会重新读取并检查。",preflight=p)
            }
            val credential=if(s.useKey){
                val b=docs.capture(s.key ?: throw StegException("缺少密钥。"),256,ctl)
                try{Credential.keyFile(b)}finally{b.fill(0)}
            }else Credential.password(s.password)
            credential.use { c ->
                if(create){
                    val bytes=if(s.operation==Operation.HIDE)engine.hide(cover!!,doc.name,input,c,autoExpand=s.autoExpand) else engine.encrypt(doc.name,input,c)
                    try{
                        val file=stage(bytes)
                        ctl.report("保存后认证验证")
                        val saved=file.inputStream().use{BoundedIo.read(it,limits.maxContainerBytes,ctl)}
                        try{
                            val decoded=engine.decode(saved,c)
                            try {if(!decoded.data.contentEquals(input) || decoded.filename!=doc.name)throw StegException("保存后恢复验证不匹配。")}
                            finally {decoded.data.fill(0)}
                        }finally{saved.fill(0)}
                        val gif=s.operation==Operation.HIDE && GifCarrier.isGif(bytes)
                        return JobResult("成品已验证，等待保存",doc.name,doc.name,
                            if(gif)"GIF 原动画已保留，隐藏内容已认证。请另存为新文件并按文件发送；重编码可能删除密文扩展。认证保护隐藏文件，不认证动画本身。"
                            else "请通过系统文件选择器另存为新文件。请勿把隐写 PNG 作为压缩图片发送。",
                            contentHash=sha256(input),containerHash=sha256(bytes),staged=file,
                            suggestedName=when{gif->"moyle_hidden.gif";s.operation==Operation.HIDE->"moyle_hidden.png";else->"moyle_encrypted.saes"},
                            mime=when{gif->"image/gif";s.operation==Operation.HIDE->"image/png";else->"application/octet-stream"},protectedUris=protected,outputHash=sha256(bytes))
                    }finally{bytes.fill(0)}
                }
                val decoded=engine.decode(input,c)
                try{
                    val contentHash=decoded.contentSha256;val fullHash=sha256(input)
                    if(s.operation==Operation.VERIFY)return JobResult("验证通过",doc.name,decoded.filename,
                        "认证与容器摘要均对应同一份已读取数据。认证保护隐藏内容，不认证外层图片或动画；容器摘要标识整个输入。没有向共享存储写出明文；此状态不保证原路径未来不变。",
                        contentHash=contentHash,containerHash=fullHash)
                    val suggested=try{safeFilename(decoded.filename).let { if(it.toByteArray(Charsets.UTF_8).size<=180)it else "recovered.bin" }}catch(_: StegException){"recovered.bin"}
                    return JobResult("恢复内容已验证，等待保存",doc.name,decoded.filename,
                        "恢复数据暂存在应用私有区；请另存到新文件。",contentHash=contentHash,containerHash=fullHash,
                        staged=stage(decoded.data),suggestedName=suggested,protectedUris=protected,outputHash=contentHash)
                }finally{decoded.data.fill(0)}
            }
        }finally{input.fill(0);cover?.fill(0)}
    }
    private fun credential(s:UiState,ctl:Control):Credential {
        if(!s.useKey)return Credential.password(s.password)
        val bytes=docs.capture(s.key ?: throw StegException("缺少密钥。"),256,ctl)
        return try{Credential.keyFile(bytes)}finally{bytes.fill(0)}
    }
    private fun processFile(s:UiState,doc:PickedDocument,ctl:Control,protected:List<Uri>,onStaged:(File)->Unit):JobResult {
        val fileLimits=FileLimits()
        val encrypt=s.operation==Operation.ENCRYPT
        val input=docs.captureFile(doc,if(encrypt)fileLimits.maxPayloadBytes else fileLimits.maxContainerBytes,ctl)
        try{
            credential(s,ctl).use{c->
                val engine=SaesFiles(fileLimits,ctl)
                val r=when(s.operation){
                    Operation.ENCRYPT->engine.encrypt(input,doc.name,c,docs.workDirectory())
                    Operation.VERIFY->engine.verify(input,c,docs.workDirectory())
                    else->engine.decrypt(input,c,docs.workDirectory())
                }
                // Establish ownership before returning across a cancellable coroutine boundary.
                r.output?.let(onStaged)
                r.output?.let{docs.validateStaged(it,if(encrypt)r.containerSha256 else r.payloadSha256,ctl)}
                val suggestion=if(encrypt)"moyle_encrypted.saes" else try{
                    safeFilename(r.filename).takeIf{it.toByteArray(Charsets.UTF_8).size<=180} ?: "recovered.bin"
                }catch(_:StegException){"recovered.bin"}
                return JobResult(if(r.output==null)"验证通过" else if(encrypt)"SAES 成品已验证，等待保存" else "恢复内容已验证，等待保存",
                    doc.name,r.filename,
                    if(r.output==null)"已完整认证本次捕获的 SAES；原文摘要与容器摘要针对同一份数据。验证未生成明文文件。"
                    else "采用分块文件处理，原文件 ${MemoryPolicy.mib(r.originalBytes)} MiB。私有成品已验证；请另存为新文件，导出后还会回读校验。",
                    contentHash=r.payloadSha256,containerHash=r.containerSha256,staged=r.output,
                    suggestedName=suggestion,protectedUris=protected,outputHash=if(encrypt)r.containerSha256 else r.payloadSha256)
            }
        }finally{input.delete()}
    }
    fun export(uri: Uri){
        val r=_state.value.result ?: return
        val file=r.staged ?: return
        if(_state.value.busy || _state.value.selecting)return
        cancel.set(false);_state.update{it.copy(busy=true,error=null,stage="保存到所选位置")}
        job=viewModelScope.launch {
            try{
                withContext(Dispatchers.IO){
                    val ctl=control(currentCoroutineContext())
                    val expected=r.outputHash
                    docs.validateStaged(file,expected,ctl)
                    docs.export(file,uri,r.protectedUris,expected,ctl)
                }
                _state.update{it.copy(busy=false,result=r.copy(title="已保存并回读校验",exportedUri=uri),stage="完成")}
            }catch(_: CancellationException){throw CancellationException()}
            catch(e: Exception){_state.update{it.copy(busy=false,error=if(e is StegException)e.message else "无法完成导出，请检查文档提供方与存储空间。")}}
            finally{_state.update{it.copy(busy=false)}}
        }
    }
    override fun onCleared(){cancel.set(true);_state.value.result?.staged?.delete();super.onCleared()}
}
