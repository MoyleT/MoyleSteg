package com.moyle.steg.android

import android.app.Application
import android.net.Uri
import android.os.CancellationSignal
import android.os.OperationCanceledException
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
data class RestoredMember(val entry:BundleEntry,val selected:Boolean=true,
    val saved:SavedDownload?=null,val error:String?=null)
data class JobResult(
    val title: String,val inputLabel: String,val filename: String,val message: String,
    val contentHash: String="",val containerHash: String="",val at: String=now(),
    val staged: File?=null,val suggestedName: String="result.bin",val mime: String="application/octet-stream",
    val protectedUris: List<Uri> = emptyList(),val outputHash: String="",val exportedUri: Uri?=null,
    val preflight: Preflight?=null,
    val restored: Boolean=false,val download: SavedDownload?=null,
    val downloadIssue: String?=null,val needsStoragePermission: Boolean=false,
    val bundle:BundleInfo?=null,val members:List<RestoredMember> = emptyList(),
    val bundleBudget:Long=32L*1024*1024
)
fun now(): String = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
data class DiscardRequest(val page:Int?,val operation:Operation?,val result:JobResult)
data class UiState(
    val page: Int=0,val operation: Operation=Operation.HIDE,
    val input: PickedDocument?=null,val cover: PickedDocument?=null,val key: PickedDocument?=null,
    val inputs:List<PickedDocument> = emptyList(),val inputSizes:Map<Uri,Long?> = emptyMap(),
    val useKey: Boolean=false,val password: String="",val confirmation: String="",val autoExpand: Boolean=true,
    val theme: String="midnight",val largeText: Boolean=false,
    val manualMemory:Boolean=false,val manualMemoryMiB:String="128",val resourceAcknowledged:Boolean=false,
    val memorySnapshot:MemorySnapshot?=null,val memoryPlan:MemoryPlan?=null,val resourceError:String?=null,
    val inputProbe:DocumentProbe?=null,val coverProbe:DocumentProbe?=null,
    val busy: Boolean=false,val selecting: Boolean=false,val stage: String="",val completed: Int=0,val total: Int=0,
    val error: String?=null,val result: JobResult?=null,
    val downloadPermissionRequest: Long?=null,val discardRequest:DiscardRequest?=null
)

class MoyleViewModel @JvmOverloads constructor(application: Application,
    private val downloads: DownloadWriter=DownloadsExporter(application),
    private val privateSpace:(File)->Long={it.usableSpace},
    private val memoryReader:()->MemorySnapshot={DeviceResources.snapshot(application)}): AndroidViewModel(application) {
    private val docs=DocumentStore(application,privateSpace)
    private val bundleDisk=BundleDiskPolicy(privateSpace)
    private val prefs=application.getSharedPreferences("appearance",0)
    private val _state=MutableStateFlow(UiState(theme=prefs.getString("theme","midnight") ?: "midnight",largeText=prefs.getBoolean("large",false)))
    val state: StateFlow<UiState> = _state.asStateFlow()
    private val cancel=AtomicBoolean(false)
    private var job: Job?=null
    private var permissionSequence=0L
    private var permissionPending: Pair<Long,JobResult>?=null
    private var exportSequence=0L
    private var exportPending:Pair<Long,JobResult>?=null
    init { refreshResources() }
    fun refreshResources(){
        if(_state.value.busy)return
        val observed=memoryReader();val s=_state.value
        val planned=runCatching{MemoryPolicy.choose(observed,s.manualMemory,s.manualMemoryMiB.toIntOrNull() ?: 0)}
        _state.update{it.copy(memorySnapshot=observed,memoryPlan=planned.getOrNull(),resourceError=planned.exceptionOrNull()?.message)}
    }
    fun manualMemory(value:Boolean){if(!_state.value.busy){_state.update{it.copy(manualMemory=value,resourceAcknowledged=false)};refreshResources()}}
    fun manualMemoryMiB(value:String){if(!_state.value.busy){_state.update{it.copy(manualMemoryMiB=value.filter(Char::isDigit).take(4),resourceAcknowledged=false)};refreshResources()}}
    fun acknowledgeResources(value:Boolean){if(!_state.value.busy)_state.update{it.copy(resourceAcknowledged=value)}}
    // Accessed on the main thread. Each slot owns its latest metadata request.
    private var selectionSequence=0L
    private val selections=mutableMapOf<DocSlot,Long>()
    private class SelectionTask(val signal:CancellationSignal=CancellationSignal(),var job:Job?=null){
        fun cancel(){
            job?.cancel()
            // Provider cancellation and closing its stream may themselves block.
            // Cancel our coroutine immediately, and dispatch that external work off UI.
            Dispatchers.IO.dispatch(kotlin.coroutines.EmptyCoroutineContext,Runnable{signal.cancel()})
        }
    }
    private val selectionTasks=mutableMapOf<DocSlot,SelectionTask>()
    private fun invalidateSelections() {
        selections.clear()
        val old=selectionTasks.values.toList();selectionTasks.clear()
        old.forEach{it.cancel()}
        _state.update { it.copy(selecting=false,resourceAcknowledged=false) }
    }
    private fun newSelection(slot:DocSlot):Pair<Long,SelectionTask>{
        selections.remove(slot)
        selectionTasks.remove(slot)?.cancel()
        val revision=++selectionSequence;val task=SelectionTask()
        selections[slot]=revision;selectionTasks[slot]=task
        return revision to task
    }
    fun cancelSelection(){if(!_state.value.busy)invalidateSelections()}
    fun page(value: Int) {
        val s=_state.value
        if(s.busy || value !in 0..3 || value==s.page)return
        if(value==3 || value==operationPage(s.operation)){
            _state.update{it.copy(page=value,password="",confirmation="",resourceAcknowledged=false,discardRequest=null)}
            return
        }
        val next=when(value){0->Operation.HIDE;1->Operation.RESTORE;else->Operation.ENCRYPT}
        requestNavigation(value,next)
    }
    fun operation(value: Operation) {
        if(_state.value.busy || value==_state.value.operation)return
        requestNavigation(operationPage(value),value)
    }
    fun operationPage(value:Operation=_state.value.operation):Int=when(value){
        Operation.HIDE->0;Operation.RESTORE,Operation.VERIFY->1;else->2
    }
    private fun hasUnsavedResult(r:JobResult?):Boolean = r?.staged!=null && r.exportedUri==null &&
        r.download==null && (r.bundle==null || r.members.any{it.saved==null})
    private fun requestNavigation(page:Int,operation:Operation){
        val result=_state.value.result
        if(hasUnsavedResult(result)){
            _state.update{it.copy(discardRequest=DiscardRequest(page,operation,result!!))}
        }else applyNavigation(page,operation)
    }
    private fun applyNavigation(page:Int,operation:Operation){
        invalidateSelections();clearResult();clearMultipleSelection()
        _state.update{it.copy(page=page,operation=operation,password="",confirmation="",error=null)}
    }
    fun requestClearResult(){
        if(_state.value.busy)return
        val result=_state.value.result
        if(hasUnsavedResult(result))_state.update{it.copy(discardRequest=DiscardRequest(null,null,result!!))}
        else clearResult()
    }
    fun keepCurrentWork(){_state.update{it.copy(discardRequest=null)}}
    fun confirmDiscard(){
        val s=_state.value;val pending=s.discardRequest ?: return
        if(s.busy)return
        if(s.result!==pending.result){keepCurrentWork();return}
        if(pending.page!=null && pending.operation!=null)applyNavigation(pending.page,pending.operation)
        else clearResult()
    }
    fun setPassword(value: String){if(!_state.value.busy)_state.update{it.copy(password=value.take(2048))}}
    fun setConfirmation(value: String){if(!_state.value.busy)_state.update{it.copy(confirmation=value.take(2048))}}
    fun useKey(value: Boolean){if(!_state.value.busy){invalidateSelections();clearResult();_state.update{it.copy(useKey=value,password="",confirmation="")}}}
    fun autoExpand(value: Boolean){if(!_state.value.busy){clearResult();_state.update{it.copy(autoExpand=value)}}}
    fun theme(value: String){prefs.edit().putString("theme",value).apply();_state.update{it.copy(theme=value)}}
    fun largeText(value: Boolean){prefs.edit().putBoolean("large",value).apply();_state.update{it.copy(largeText=value)}}
    fun clearPasswords(){_state.update{it.copy(password="",confirmation="")}}
    fun clearResult(){if(!_state.value.busy){
        permissionPending=null
        exportPending=null
        _state.value.result?.staged?.delete()
        _state.update{it.copy(result=null,error=null,downloadPermissionRequest=null,discardRequest=null)}
    }}
    fun requestCancel(){cancel.set(true);_state.update{it.copy(stage="正在等待安全取消点…")}}
    fun pick(slot: DocSlot,uri: Uri){
        if(_state.value.busy)return
        clearResult()
        val (revision,task)=newSelection(slot)
        // Remove the previous input immediately; it cannot stand in for a pending selection.
        _state.update { state ->
            val next=when(slot){DocSlot.INPUT->state.copy(input=null,inputProbe=null,inputs=emptyList(),inputSizes=emptyMap());DocSlot.COVER->state.copy(cover=null,coverProbe=null);DocSlot.KEY->state.copy(key=null)}
            next.copy(selecting=true,error=null,resourceAcknowledged=false)
        }
        task.job=viewModelScope.launch(start=CoroutineStart.LAZY) {
            try{
                val (doc,probe)=withContext(Dispatchers.IO){
                    val ctx=currentCoroutineContext()
                    val ctl=Control(cancelled={task.signal.isCanceled || !ctx.isActive})
                    val described=docs.describe(uri,ctl,task.signal)
                    // A provider may supply metadata but not a preview stream. Actual jobs must still open and validate it.
                    val probe=if(slot==DocSlot.KEY)null else try{docs.probe(described,ctl,task.signal)}catch(e:Exception){
                        ctx.ensureActive();ctl.check();if(e is OperationCanceledException)throw e;null
                    }
                    described to probe
                }
                if(selections[slot]==revision && !_state.value.busy){
                    clearResult()
                    _state.update { when(slot){DocSlot.INPUT->it.copy(input=doc,inputProbe=probe);DocSlot.COVER->it.copy(cover=doc,coverProbe=probe);DocSlot.KEY->it.copy(key=doc)} }
                }
            }catch(e: CancellationException){throw e}
            catch(_:CancelledException){}
            catch(_:OperationCanceledException){}
            catch(_: Exception){if(selections[slot]==revision)_state.update{it.copy(error="无法读取选择的文件，请重新选择。")}}
            finally{
                if(selections[slot]==revision){
                    selections.remove(slot)
                    selectionTasks.remove(slot)
                    _state.update{it.copy(selecting=selections.isNotEmpty())}
                }
            }
        }
        task.job!!.start()
    }
    private fun clearMultipleSelection(){
        if(_state.value.inputs.isNotEmpty())_state.update{it.copy(input=null,inputProbe=null,inputs=emptyList(),inputSizes=emptyMap())}
    }
    fun pickInputs(uris:List<Uri>){
        val s=_state.value
        if(s.busy || s.operation !in listOf(Operation.HIDE,Operation.ENCRYPT) || uris.isEmpty())return
        val existing=s.inputs.ifEmpty{listOfNotNull(s.input)}
        val merged=(existing.map{it.uri}+uris).distinct()
        if(merged.size>100){_state.update{it.copy(error="一次最多选择 100 个文件。")};return}
        clearResult()
        val (revision,task)=newSelection(DocSlot.INPUT)
        _state.update{it.copy(selecting=true,error=null,resourceAcknowledged=false)}
        task.job=viewModelScope.launch(start=CoroutineStart.LAZY) {
            try{
                val items=withContext(Dispatchers.IO){
                    val ctx=currentCoroutineContext()
                    val ctl=Control(cancelled={task.signal.isCanceled || !ctx.isActive})
                    merged.map{uri->
                        ctl.check()
                        val doc=docs.describe(uri,ctl,task.signal)
                        val size=try{docs.probe(doc,ctl,task.signal).size}catch(e:Exception){
                            ctx.ensureActive();ctl.check();if(e is OperationCanceledException)throw e;null
                        }
                        doc to size
                    }
                }
                if(selections[DocSlot.INPUT]==revision && !_state.value.busy){
                    _state.update{it.copy(input=items.first().first,inputProbe=null,inputs=items.map{p->p.first},
                        inputSizes=items.associate{p->p.first.uri to p.second})}
                }
            }catch(e:CancellationException){throw e}
            catch(_:CancelledException){}
            catch(_:OperationCanceledException){}
            catch(_:Exception){if(selections[DocSlot.INPUT]==revision)_state.update{it.copy(error="无法读取文件列表，原选择已保留。请重新选择。")}}
            finally{if(selections[DocSlot.INPUT]==revision){selections.remove(DocSlot.INPUT);selectionTasks.remove(DocSlot.INPUT);_state.update{it.copy(selecting=selections.isNotEmpty())}}}
        }
        task.job!!.start()
    }
    fun removeInput(uri:Uri){
        if(_state.value.busy)return
        invalidateSelections();clearResult()
        _state.update{val remaining=it.inputs.ifEmpty{listOfNotNull(it.input)}.filter{d->d.uri!=uri}
            it.copy(inputs=remaining,input=remaining.firstOrNull(),inputProbe=null,inputSizes=it.inputSizes-uri)}
    }
    fun clearInputs(){if(!_state.value.busy){invalidateSelections();clearResult();_state.update{it.copy(inputs=emptyList(),input=null,inputProbe=null,inputSizes=emptyMap())}}}
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
        if(s.operation==Operation.HIDE && s.cover==null){_state.update{it.copy(error="请先选择 JPG／PNG／GIF 载体。")};return}
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
                    val processed=process(s,capacityOnly,ctl){staged=it}
                    if(s.operation==Operation.RESTORE && !capacityOnly)
                        prepareRestored(processed.copy(restored=true),ctl) else processed
                }
                currentCoroutineContext().ensureActive()
                deliverResult(result);delivered=true
            }catch(_: CancellationException){throw CancellationException()}
            catch(e: Exception){_state.update{it.copy(busy=false,error=if(e is StegException)e.message else "操作失败：请检查文件访问权限、存储空间及输入格式。",stage="未完成")}}
            finally{if(!delivered)staged?.delete();_state.update{it.copy(busy=false,password="",confirmation="",resourceAcknowledged=false)}}
        }
    }
    private fun prepareRestored(r:JobResult,ctl:Control):JobResult {
        val file=r.staged ?: throw StegException("没有可恢复的数据。")
        val info=MultiFileBundle.inspect(file,r.bundleBudget,r.bundleBudget,ctl)
            ?: return publishRestored(r,ctl)
        return r.copy(title="已认证 ${info.entries.size} 个文件",bundle=info,
            members=info.entries.map{RestoredMember(it)},mime="application/zip",suggestedName="MoyleSteg-files.zip",
            message="选择需要的文件并保存到 Download。清空结果会移除私有临时包，已经保存的文件会保留。")
    }
    fun selectRestoredMember(index:Int,selected:Boolean){
        if(_state.value.busy)return
        permissionPending=null
        _state.update{it.copy(downloadPermissionRequest=null,result=it.result?.let{r->
            r.copy(needsStoragePermission=false,members=r.members.map{m->if(m.entry.index==index && m.saved==null)m.copy(selected=selected)else m})})}
    }
    fun selectAllRestoredMembers(selected:Boolean){
        if(_state.value.busy)return
        permissionPending=null
        _state.update{it.copy(downloadPermissionRequest=null,result=it.result?.let{r->
            r.copy(needsStoragePermission=false,members=r.members.map{m->if(m.saved==null)m.copy(selected=selected)else m})})}
    }
    fun saveBundleSelection(){
        val initial=_state.value.result ?: return
        val archive=initial.staged ?: return
        if(initial.bundle==null || _state.value.busy || _state.value.selecting)return
        val chosen=initial.members.filter{it.selected && it.saved==null}
        if(chosen.isEmpty())return
        permissionPending=null;cancel.set(false)
        _state.update{it.copy(busy=true,error=null,stage="保存选中文件",downloadPermissionRequest=null)}
        job=viewModelScope.launch {
            var result=initial.copy(downloadIssue=null,needsStoragePermission=false)
            var activeIndex:Int?=null
            try{
                withContext(Dispatchers.IO){
                    val ctl=control(currentCoroutineContext())
                    docs.validateStaged(archive,initial.outputHash,ctl)
                    for(member in chosen){
                        activeIndex=member.entry.index;ctl.check()
                        ctl.report("保存文件 ${member.entry.index} / ${initial.members.size}")
                        val file=MultiFileBundle.extract(archive,member.entry,docs.workDirectory(),initial.bundleBudget,initial.bundleBudget,ctl,bundleDisk)
                        try{
                            val mime=RestoredFileActions.mimeFor(file,member.entry.name)
                            val saved=downloads.save(file,member.entry.name,mime,member.entry.sha256,ctl)
                            // Persist each committed item before observing another cancellation checkpoint.
                            result=result.copy(members=result.members.map{if(it.entry.index==member.entry.index)it.copy(saved=saved,selected=false,error=null)else it})
                            _state.update{it.copy(result=result)}
                        }finally{file.delete()}
                    }
                }
                currentCoroutineContext().ensureActive()
            }catch(e:CancellationException){throw e}
            catch(e:Exception){
                val issue=when(e){
                    is DownloadPermissionException->e.message ?: "需要保存权限。"
                    is CancelledException->"已停止保存；已完成的文件保留，剩余文件可直接重试。"
                    is StegException->e.message ?: "文件尚未保存，请重试。"
                    else->"保存未完成，请检查空间和权限。已完成的文件保留，剩余文件可直接重试。"
                }
                result=result.copy(downloadIssue=issue,needsStoragePermission=e is DownloadPermissionException,
                    members=result.members.map{if(it.entry.index==activeIndex && it.saved==null)it.copy(error=issue)else it})
            }finally{_state.update{it.copy(busy=false)}}
            val count=result.members.count{it.saved!=null}
            deliverResult(result.copy(title="已保存 $count / ${result.members.size} 个文件",at=now(),
                message="文件保存到 Download，同名文件自动另取名称。可直接打开已保存项，或继续选择剩余文件。"))
        }
    }
    /** Both authentication and private staging have succeeded before any public file is created. */
    private fun publishRestored(r:JobResult,ctl:Control):JobResult {
        val file=r.staged ?: throw StegException("没有可保存的恢复文件。")
        var mime=r.mime
        return try{
            ctl.check()
            mime=RestoredFileActions.mimeFor(file,r.filename)
            val saved=downloads.save(file,r.suggestedName,mime,r.outputHash,ctl)
            // save() returns only after commit. A late cooperative cancel cannot undo success.
            r.copy(title="已恢复并保存",message="已保存到下载文件夹。点击“打开文件”，选择你习惯的应用查看。",
                mime=saved.mime,download=saved,exportedUri=saved.uri,at=now(),downloadIssue=null,needsStoragePermission=false)
        }catch(e:CancellationException){throw e}
        catch(e:Exception){
            val issue=when(e){
                is DownloadPermissionException->e.message ?: "需要存储权限才能保存到 Download。"
                is CancelledException->"已取消保存。恢复内容已经认证，可直接重试，无需重新输入口令。"
                else->"恢复内容已经认证，但尚未保存到 Download。请重试或选择其他位置。"+
                    (if(e is StegException) "\n${e.message}" else "请检查可用空间和保存权限。")
            }
            r.copy(title="已恢复，尚未保存",message="已恢复内容暂存在应用私有区；清空结果或重新启动应用会移除这份临时内容。",
                mime=mime,download=null,exportedUri=null,downloadIssue=issue,needsStoragePermission=e is DownloadPermissionException)
        }
    }
    private fun deliverResult(result:JobResult){
        permissionPending=null
        val token=if(result.needsStoragePermission)++permissionSequence else null
        if(token!=null)permissionPending=token to result
        _state.update{it.copy(result=result,busy=false,error=result.downloadIssue,
            stage=if(result.downloadIssue==null)"完成" else "等待保存",password="",confirmation="",downloadPermissionRequest=token)}
    }
    fun consumeDownloadPermissionRequest(token:Long){
        if(_state.value.downloadPermissionRequest==token)_state.update{it.copy(downloadPermissionRequest=null)}
    }
    fun onDownloadPermissionResult(token:Long,granted:Boolean){
        val pending=permissionPending ?: return
        if(pending.first!=token)return
        permissionPending=null
        if(_state.value.result!==pending.second || _state.value.busy)return
        _state.update{it.copy(downloadPermissionRequest=null)}
        if(granted)saveRestoredToDownloads()
        else _state.update{it.copy(error="未获得保存权限。已恢复内容仍可重试；也可选择其他位置保存，无需重新输入口令。")}
    }
    fun saveRestoredToDownloads(){
        val r=_state.value.result ?: return
        if(r.bundle!=null){saveBundleSelection();return}
        if(!r.restored || r.staged==null || r.exportedUri!=null || _state.value.busy || _state.value.selecting)return
        permissionPending=null;cancel.set(false)
        _state.update{it.copy(busy=true,error=null,stage="保存到下载文件夹",downloadPermissionRequest=null)}
        job=viewModelScope.launch {
            try{
                val saved=withContext(Dispatchers.IO){publishRestored(r,control(currentCoroutineContext()))}
                currentCoroutineContext().ensureActive()
                deliverResult(saved)
            }finally{_state.update{it.copy(busy=false)}}
        }
    }
    fun reportOpenFailure(message:String){if(!_state.value.busy)_state.update{it.copy(error=message)}}
    private fun process(s: UiState,capacityOnly: Boolean,ctl: Control,onStaged: (File)->Unit): JobResult {
        val sources=s.inputs
        if(sources.size<2 || s.operation !in listOf(Operation.HIDE,Operation.ENCRYPT))return processSingle(s,capacityOnly,ctl,onStaged)
        val budget=if(s.operation==Operation.ENCRYPT)FileLimits().maxPayloadBytes else 32L*1024*1024
        var known=0L
        for(source in sources){
            val size=(s.inputSizes[source.uri] ?: 0L).coerceAtLeast(0L)
            if(size>budget-known)throw StegException("文件总大小超过本次处理上限；图片使用 32 MiB，独立 SAES 使用 1 GiB。")
            known+=size
        }
        val work=docs.workDirectory()
        val plannedZip=MultiFileBundle.plannedArchiveBytes(known,sources.size,budget)
        // ZIP capture + raw/compression candidates, or ZIP capture + encrypted output
        // and its independent verification capture: at most 3 ZIP lengths + 128 KiB.
        // The original ZIP itself is still present at that point. This estimate does
        // not reserve storage; provider sizes may be unknown/stale and are rechecked.
        val initialPeak=if(s.operation==Operation.ENCRYPT)
            maxOf(known+plannedZip,4*plannedZip+128*1024) else known+plannedZip
        ctl.report("检查多文件临时空间（估算 ${((initialPeak+1048575)/1048576)} MiB，另留 32 MiB）")
        bundleDisk.requireAdditional(work,initialPeak)
        val captured=mutableListOf<File>();var archive:File?=null
        try{
            var total=0L
            val inputs=sources.mapIndexed{index,doc->
                ctl.report("读取文件 ${index+1} / ${sources.size}")
                val file=docs.captureFile(doc,(budget-total).coerceAtLeast(1L),ctl);captured.add(file)
                total+=file.length()
                if(total>budget)throw StegException("文件总大小超过处理预算。")
                BundleSource(file,doc.name)
            }
            val pack=MultiFileBundle.create(inputs,work,budget,budget,ctl,bundleDisk);archive=pack.file
            // The verified ZIP now owns the captured content; release duplicate inputs
            // before the subsequent encryption workspace is allocated.
            for(file in captured)if(file.exists() && !file.delete())throw StegException("无法清理已完成打包的私有输入副本。")
            captured.clear()
            if(s.operation==Operation.ENCRYPT){
                ctl.report("检查加密暂存空间")
                bundleDisk.requireAdditional(work,3*pack.info.archiveBytes+128*1024)
            }
            val guarded=Control(progress={stage,done,extent->ctl.report(stage,done,extent)},
                cancelled={ctl.check();bundleDisk.requireAdditional(work,0);false})
            val r=processSingle(s.copy(input=PickedDocument(Uri.fromFile(pack.file),"MoyleSteg-files.zip"),inputs=emptyList()),capacityOnly,guarded,onStaged)
            return r.copy(inputLabel="${sources.size} 个文件："+sources.joinToString("、"){it.name},
                protectedUris=(sources.map{it.uri}+listOfNotNull(s.cover?.uri,s.key?.uri)).distinct(),
                message="${sources.size} 个文件 · 原始合计 ${pack.info.totalBytes} 字节 · 实际 ZIP ${pack.info.archiveBytes} 字节\n"+r.message)
        }catch(e:java.io.IOException){throw bundleDisk.mapFailure(e)}
        finally{captured.forEach{it.delete()};archive?.delete()}
    }
    private fun processSingle(s: UiState,capacityOnly: Boolean,ctl: Control,onStaged: (File)->Unit): JobResult {
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
        var coverPixels: RgbaImage?=null
        var isJpegCover=false
        try{
            if(s.operation==Operation.HIDE){
                cover=docs.capture(s.cover ?: throw StegException("缺少载体。"),captureLimit(limits.maxContainerBytes,coverInfo,input.size.toLong()),ctl)
                checkImage(docs.probeBytes(cover,control=ctl),input.size.toLong())
                // JPEG is a creation input only. Existing containers always retain their exact samples.
                isJpegCover=JpegCarrier.isJpeg(cover)
                if(isJpegCover)coverPixels=JpegCarrier.decode(cover,limits,ctl,input.size.toLong())
            }else checkImage(docs.probeBytes(input,control=ctl))
            if(capacityOnly){
                val p=coverPixels?.let{engine.preflightPixels(it,cover!!.size,doc.name,input,autoExpand=s.autoExpand)}
                    ?: engine.preflight(cover ?: throw StegException("缺少载体。"),doc.name,input,autoExpand=s.autoExpand)
                if(p.format=="gif")return JobResult(if(p.fits)"GIF 预算检查通过"else "GIF 超出成品预算",doc.name,doc.name,
                    "GIF 动画：${p.frameCount} 帧 · ${p.width} × ${p.height}\n预计成品：${p.outputBytes} 字节\n原文件：${p.originalBytes} 字节\n压缩：${if(p.compressed)"是"else "否"}\n"+
                        "保留原动画，不改变尺寸。密文存储于标准扩展块，可被文件分析识别，重编码可能删除它；请按文件发送。\n"+
                        "预检不预留资源；执行时会重新读取并检查。",preflight=p)
                val occupancy=if(p.capacityBytes==0)"无可用容量" else String.format(Locale.ROOT,"%.1f%%",p.occupancyPercent)
                val memory=String.format(Locale.ROOT,"%.1f",p.estimatedWorkingBytes/1048576.0)
                return JobResult(when{!p.fits->"容量不足";p.expanded->"扩容后容量足够";else->"容量足够"},doc.name,doc.name,
                    (if(isJpegCover)"JPG → PNG · 已按照片方向校正\n"else "")+
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
                    val bytes=if(s.operation==Operation.HIDE)
                        coverPixels?.let{engine.hidePixels(it,cover!!.size,doc.name,input,c,autoExpand=s.autoExpand)}
                            ?: engine.hide(cover!!,doc.name,input,c,autoExpand=s.autoExpand)
                        else engine.encrypt(doc.name,input,c)
                    // The consuming pixel API already wiped its buffer. Release its reference
                    // before the saved PNG is decoded into a second full image for verification.
                    coverPixels=null
                    cover?.fill(0)
                    cover=null
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
                            else (if(isJpegCover)"JPG 载体已转换为 PNG 成品；照片方向已校正，原 JPG 保持不变。\n"else "")+
                                "请通过系统文件选择器另存为新文件。发送时保留原文件，接收后可用只读验证核对；压缩或重新编码可能破坏内容。",
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
        }finally{input.fill(0);cover?.fill(0);coverPixels?.rgba?.fill(0)}
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
                    suggestedName=suggestion,protectedUris=protected,outputHash=if(encrypt)r.containerSha256 else r.payloadSha256,
                    bundleBudget=fileLimits.maxPayloadBytes)
            }
        }finally{input.delete()}
    }
    fun requestExport():Long?{
        val r=_state.value.result ?: return null
        if(r.staged==null || _state.value.busy || _state.value.selecting)return null
        return (++exportSequence).also{exportPending=it to r}
    }
    fun completeExport(token:Long,uri:Uri?){
        val pending=exportPending ?: return
        if(token!=pending.first)return
        exportPending=null
        if(uri!=null && _state.value.result===pending.second)export(uri)
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
                permissionPending=null
                _state.update{it.copy(busy=false,result=r.copy(title="已保存并回读校验",exportedUri=uri,download=null,
                    message=if(r.restored)"已保存到你选择的位置，点击“打开文件”选择应用查看。" else r.message,
                    downloadIssue=null,needsStoragePermission=false),stage="完成",downloadPermissionRequest=null)}
            }catch(_: CancellationException){throw CancellationException()}
            catch(e: Exception){_state.update{it.copy(busy=false,error=if(e is StegException)e.message else "无法完成导出，请检查文档提供方与存储空间。")}}
            finally{_state.update{it.copy(busy=false)}}
        }
    }
    override fun onCleared(){cancel.set(true);invalidateSelections();_state.value.result?.staged?.delete();super.onCleared()}
}
