import {useEffect,useState} from "react";
import {Check,Clock3,FileText,Save,X} from "lucide-react";
import {get,request} from "./api";

type Revision = {
  version:number;action:string;actor_user_id:string;
  old_content:string|null;new_content:string|null;
  source_message_id:string|null;occurred_at:string;
};
type RecordDetail = {
  memory:{
    id:string;content:string;status:string;source_message_id:string|null;
    source_content:string|null;source_title:string|null;import_provider:string|null;
    import_source_id:string|null;
  };
  revisions:Revision[];
};
type Props = {
  projectId:string;memoryId:string;onClose:()=>void;onSaved:()=>Promise<void>;
};

export default function MemoryDetail({projectId,memoryId,onClose,onSaved}:Props){
  const [detail,setDetail]=useState<RecordDetail|null>(null);
  const [draft,setDraft]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  async function load(){
    const item=await get<RecordDetail>(
      `/v1/projects/${projectId}/memories/${memoryId}/history`
    );
    setDetail(item);
    setDraft(item.memory.content);
  }
  useEffect(()=>{
    setDetail(null);setError("");
    void load().catch(e=>setError(String(e)));
  },[projectId,memoryId]);

  async function save(){
    if(!detail||!draft.trim()||busy)return;
    setBusy(true);setError("");
    try{
      await request(`/v1/projects/${projectId}/memories/${memoryId}`,{
        method:"PUT",
        body:JSON.stringify({
          content:draft.trim(),
          expectedVersion:detail.revisions[0]?.version||1,
        }),
      });
      await load();
      await onSaved();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }

  return <section className="memory-detail">
    <header className="memory-detail-header">
      <strong><Clock3 size={14}/> 기억 변경 이력</strong>
      <button type="button" aria-label="이력 닫기" onClick={onClose}><X size={15}/></button>
    </header>
    {error&&<p className="codex-error" role="alert">{error}</p>}
    {detail&&<>
      <p className="codex-hint">현재 상태: {detail.memory.status==="active"?"사용 중":"철회됨"} · {detail.revisions.length}개 기록</p>
      <label className="codex-label" htmlFor="memory-update">승인된 기억 내용</label>
      <textarea id="memory-update" rows={3} maxLength={2000}
        value={draft} disabled={detail.memory.status!=="active"}
        onChange={e=>setDraft(e.target.value)}/>
      {detail.memory.status==="active"&&<button className="memory-save"
        onClick={()=>void save()}
        disabled={busy||!draft.trim()||draft.trim()===detail.memory.content}>
        <Save size={13}/> 변경 저장
      </button>}
      {detail.memory.source_message_id&&<div className="memory-origin">
        <strong><FileText size={13}/> 원본 출처</strong>
        <p>{detail.memory.import_provider||"Gleave 채팅"} · {detail.memory.source_title||"제목 없음"}</p>
        {detail.memory.import_source_id&&<p>원본 대화 ID: <code>{detail.memory.import_source_id}</code></p>}
        <p className="memory-origin-quote">{detail.memory.source_content||"원본 메시지가 삭제됨"}</p>
      </div>}
      <div className="memory-revision-list">
        {detail.revisions.map(r=><div key={r.version} className="memory-revision">
          <strong><Check size={12}/> v{r.version} · {
            r.action==="created"?"생성":r.action==="updated"?"수정":
              r.action==="revoked"?"철회":"기존 기록 스냅샷"
          }</strong>
          <small>{new Date(r.occurred_at).toLocaleString("ko-KR")} · {r.actor_user_id}</small>
          {r.old_content!==null&&<p className="memory-revision-before">이전: {r.old_content}</p>}
          {r.new_content!==null&&<p>현재: {r.new_content}</p>}
        </div>)}
      </div>
    </>}
  </section>;
}
