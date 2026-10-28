import {useEffect,useState} from "react";
import {BrainCircuit,Check,Lightbulb,ShieldAlert,X} from "lucide-react";
import {get,post} from "./api";

type Verdict="new"|"duplicate"|"conflict"|"uncertain";
type Analysis={
  sourceMessageId:string;verdict:Verdict;suggestedText:string;reason:string;
  relatedMemoryIds:string[];relatedMemories:Array<{id:string;text:string}>;
  provider:string;model:string|null;method:string;
};
type Candidate={
  sourceMessageId:string;sourceTitle:string;sourceProvider:string;
  suggestedText:string;reason:string;method:string;analysis?:Analysis|null;
};
type Provider={id:string;label:string;available:boolean};
type Props={projectId:string;onApproved:()=>Promise<void>};

const verdictLabel:Record<Verdict,string>={
  new:"새로운 기억 후보",duplicate:"기존 기억과 중복 가능성",
  conflict:"기존 기억과 충돌 가능성",uncertain:"판단 보류",
};

export default function MemoryCandidates({projectId,onApproved}:Props){
  const [items,setItems]=useState<Candidate[]>([]);
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const [providers,setProviders]=useState<Provider[]>([]);
  const [provider,setProvider]=useState("gpt");
  const [consent,setConsent]=useState(false);
  const [acknowledged,setAcknowledged]=useState<Record<string,boolean>>({});
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
      setDrafts(Object.fromEntries(result.items.map(c=>[
        c.sourceMessageId,c.analysis?.suggestedText||c.suggestedText
      ])));
      setError("");
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setLoading(false);}
  }
  useEffect(()=>{
    setConsent(false);setAcknowledged({});setItems([]);setError("");
    void reload();
    void get<{items:Provider[]}>("/v1/providers")
      .then(result=>{
        const available=result.items.filter(p=>
          ["gpt","claude","ollama"].includes(p.id)&&p.available
        );
        setProviders(available);
        setProvider(available[0]?.id||"gpt");
      }).catch(err=>setError(String(err)));
  },[projectId]);

  async function analyze(item:Candidate){
    if(!consent||!providers.some(p=>p.id===provider))return;
    setActive(item.sourceMessageId);setError("");
    try{
      const analysis=await post<Analysis>(
        `/v1/imports/projects/${projectId}/memory-candidates/${item.sourceMessageId}/analyze`,
        {provider,consent:true}
      );
      setItems(old=>old.map(c=>c.sourceMessageId===item.sourceMessageId?
        {...c,analysis}:c
      ));
      if(analysis.suggestedText.trim()){
        setDrafts(old=>({...old,[item.sourceMessageId]:analysis.suggestedText}));
      }
      setAcknowledged(old=>({...old,[item.sourceMessageId]:false}));
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setActive(null);}
  }

  async function replaceExisting(item:Candidate,memoryId:string){
    if(item.analysis?.verdict!=="conflict"||!acknowledged[item.sourceMessageId]||active!==null)return;
    const content=drafts[item.sourceMessageId]?.trim();
    if(!content||content.length>2000)return;
    setActive(item.sourceMessageId);setError("");
    try{
      const history=await get<{memory:{content:string,status:string};revisions:{version:number}[]}>(
        `/v1/projects/${projectId}/memories/${memoryId}/history`
      );
      if(history.memory.status!=="active")throw new Error("기존 기억이 이미 철회되었습니다.");
      if(!window.confirm(
        "기존 기억을 새 결정으로 교체할까요?\n\n현재: "+
        history.memory.content+"\n\n변경: "+content+
        "\n\n이전 내용과 출처는 변경 이력에 남습니다."
      ))return;
      await post(
        `/v1/imports/projects/${projectId}/memory-candidates/${item.sourceMessageId}/replace`,
        {
          memoryId,content,expectedVersion:history.revisions[0]?.version||1,
          acknowledgedRisk:true
        }
      );
      setItems(old=>old.filter(c=>c.sourceMessageId!==item.sourceMessageId));
      await onApproved();
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setActive(null);}
  }

  async function review(item:Candidate,decision:"approve"|"dismiss"){
    const content=drafts[item.sourceMessageId]?.trim();
    if(decision==="approve"&&(!content||content.length>2000))return;
    const risky=item.analysis?.verdict==="conflict"||item.analysis?.verdict==="duplicate";
    if(decision==="approve"&&risky&&!acknowledged[item.sourceMessageId])return;
    if(decision==="approve"&&!window.confirm(
      "이 문장을 프로젝트의 공용 기억으로 확정할까요? 같은 프로젝트의 다른 채팅과 AI 모델이 참고할 수 있습니다."
    ))return;
    setActive(item.sourceMessageId);setError("");
    try{
      await post(
        `/v1/imports/projects/${projectId}/memory-candidates/${item.sourceMessageId}/review`,
        {decision,content:decision==="approve"?content:undefined,
          acknowledgedRisk:decision==="approve"&&risky&&Boolean(acknowledged[item.sourceMessageId])}
      );
      setItems(old=>old.filter(c=>c.sourceMessageId!==item.sourceMessageId));
      if(decision==="approve")await onApproved();
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setActive(null);}
  }

  return <section className="candidate-section">
    <div className="candidate-title"><Lightbulb size={15}/> 프로젝트 기억 후보 검토</div>
    <p className="codex-hint">
      가져온 사용자 메시지를 로컬 규칙으로 찾아요. AI 분석은 선택 사항이며,
      중복·상충 판정은 참고용일 뿐 확정된 사실이 아닙니다.
    </p>
    <div className="candidate-ai-controls">
      <label htmlFor="candidate-provider">분석 모델</label>
      <select id="candidate-provider" value={provider}
        disabled={providers.length===0||active!==null}
        onChange={event=>{setProvider(event.target.value);setConsent(false);}}>
        {providers.length===0?<option value="gpt">연결된 분석 모델 없음</option>:
          providers.map(p=><option key={p.id} value={p.id}>{p.label}</option>)}
      </select>
      <label className="candidate-consent">
        <input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>
        <span>선택한 후보 메시지와 기존 승인 기억 일부를 분석 모델에 전달하는 데 동의합니다.
          GPT·Claude는 외부 서버에서 처리될 수 있습니다.</span>
      </label>
    </div>
    <button type="button" className="candidate-refresh" onClick={()=>void reload()} disabled={loading}>
      {loading?"후보 조회 중":"후보 새로고침"}
    </button>
    {error&&<p className="codex-error" role="alert">{error}</p>}
    {items.length===0&&!loading&&<p className="codex-hint">현재 검토할 후보가 없습니다.</p>}
    {items.map(item=>{
      const warning=item.analysis?.verdict==="conflict"||item.analysis?.verdict==="duplicate";
      return <div className="candidate-card" key={item.sourceMessageId}>
        <div className="candidate-source">{item.sourceProvider} · {item.sourceTitle}</div>
        <textarea aria-label="기억 후보 편집" rows={3}
          value={drafts[item.sourceMessageId]??item.suggestedText}
          onChange={e=>setDrafts(old=>({...old,[item.sourceMessageId]:e.target.value}))}/>
        <p className="codex-hint">발견 이유: {item.reason}</p>
        <button className="candidate-ai-button"
          disabled={active!==null||!consent||providers.length===0}
          onClick={()=>void analyze(item)}>
          <BrainCircuit size={14}/>
          {active===item.sourceMessageId?"분석/검토 중...":"선택한 AI로 중복·충돌 분석"}
        </button>
        {item.analysis&&<div className={warning?"candidate-analysis warning":"candidate-analysis"}>
          <div className="candidate-title">
            {warning&&<ShieldAlert size={15}/>}
            {verdictLabel[item.analysis.verdict]}
          </div>
          <p>{item.analysis.reason}</p>
          {item.analysis.relatedMemories.map(note=>
            <div className="candidate-related" key={note.id}>
              <strong>비교한 기존 기억</strong><p>{note.text}</p>
              {item.analysis?.verdict==="conflict"&&<button
                className="candidate-replace-button"
                disabled={active!==null||!acknowledged[item.sourceMessageId]||
                  !(drafts[item.sourceMessageId]||"").trim()}
                onClick={()=>void replaceExisting(item,note.id)}>
                기존 기억을 새 결정으로 교체
              </button>}
            </div>
          )}
          <p className="codex-hint">
            {item.analysis.provider} · AI 제안, 사실 검증이 아님
          </p>
        </div>}
        {warning&&<label className="candidate-consent candidate-risk">
          <input type="checkbox" checked={Boolean(acknowledged[item.sourceMessageId])}
            onChange={e=>setAcknowledged(old=>({
              ...old,[item.sourceMessageId]:e.target.checked
            }))}/>
          <span>기존 기억과의 중복·충돌 가능성을 확인했습니다. 그래도 이 내용을 승인하겠습니다.</span>
        </label>}
        <div className="candidate-buttons">
          <button disabled={active!==null} onClick={()=>void review(item,"dismiss")}>
            <X size={13}/> 제외
          </button>
          <button disabled={active!==null||!(drafts[item.sourceMessageId]||"").trim()||
            (drafts[item.sourceMessageId]||"").length>2000||
            Boolean(warning&&!acknowledged[item.sourceMessageId])}
            onClick={()=>void review(item,"approve")}><Check size={13}/> 검토 후 승인</button>
        </div>
      </div>;
    })}
  </section>;
}
