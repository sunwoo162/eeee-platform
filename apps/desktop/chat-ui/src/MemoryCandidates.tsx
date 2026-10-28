import {useEffect,useState} from "react";
import {Check,Lightbulb,X} from "lucide-react";
import {get,post} from "./api";

type Candidate = {
  sourceMessageId:string;sourceTitle:string;sourceProvider:string;
  suggestedText:string;reason:string;method:string;
};
type Props={projectId:string;onApproved:()=>Promise<void>};

export default function MemoryCandidates({projectId,onApproved}:Props){
  const [items,setItems]=useState<Candidate[]>([]);
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const [loading,setLoading]=useState(false);
  const [active,setActive]=useState<string|null>(null);
  const [error,setError]=useState("");

  async function reload(){
    setLoading(true);
    try{
      const result=await get<{items:Candidate[]}>(
        `/v1/imports/projects/${projectId}/memory-candidates`
      );
      setItems(result.items);
      setDrafts(Object.fromEntries(result.items.map(c=>[c.sourceMessageId,c.suggestedText])));
      setError("");
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setLoading(false);}
  }
  useEffect(()=>{void reload();},[projectId]);

  async function review(item:Candidate,decision:"approve"|"dismiss"){
    const content=drafts[item.sourceMessageId]?.trim();
    if(decision==="approve"&&(!content||content.length>2000))return;
    if(decision==="approve"&&!window.confirm(
      "이 문장을 프로젝트의 공용 기억으로 승인할까요? 연결된 다른 채팅과 AI 모델에서 참고할 수 있습니다."
    ))return;
    setActive(item.sourceMessageId);
    try{
      await post(`/v1/imports/projects/${projectId}/memory-candidates/${item.sourceMessageId}/review`,{
        decision,content:decision==="approve"?content:undefined,
      });
      setItems(old=>old.filter(c=>c.sourceMessageId!==item.sourceMessageId));
      if(decision==="approve")await onApproved();
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setActive(null);}
  }

  return <section className="candidate-section">
    <div className="candidate-title"><Lightbulb size={15}/> 기억 후보 검토</div>
    <p className="codex-hint">가져온 사용자 발언에서 프로젝트 결정을 추리는 <strong>로컬 규칙 기반 후보</strong>입니다. AI의 사실 검증 결과가 아니며 승인 전에는 공유되지 않습니다.</p>
    <button type="button" className="candidate-refresh" onClick={()=>void reload()} disabled={loading}>
      {loading?"검토 목록 조회 중":"후보 새로고침"}
    </button>
    {error&&<p className="codex-error" role="alert">{error}</p>}
    {items.length===0&&!loading&&<p className="codex-hint">현재 검토할 후보가 없습니다.</p>}
    {items.map(item=><div className="candidate-card" key={item.sourceMessageId}>
      <div className="candidate-source">{item.sourceProvider} · {item.sourceTitle}</div>
      <textarea aria-label="기억 후보 편집" rows={3}
        value={drafts[item.sourceMessageId]??item.suggestedText}
        onChange={e=>setDrafts(old=>({...old,[item.sourceMessageId]:e.target.value}))}/>
      <p className="codex-hint">제안 이유: {item.reason}</p>
      <div className="candidate-buttons">
        <button disabled={active!==null} onClick={()=>void review(item,"dismiss")}>
          <X size={13}/> 제외
        </button>
        <button disabled={active!==null||!(drafts[item.sourceMessageId]||"").trim()||
          (drafts[item.sourceMessageId]||"").length>2000}
          onClick={()=>void review(item,"approve")}><Check size={13}/> 검토 후 승인</button>
      </div>
    </div>)}
  </section>;
}
