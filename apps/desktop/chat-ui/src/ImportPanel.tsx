import { ChangeEvent, FormEvent, useState } from "react";
import { FileJson, Folder, UploadCloud, X } from "lucide-react";
import { Project, post } from "./api";

type Format = "chatgpt"|"claude"|"codex";
type Preview = {index:number;provider:string;title:string;messageCount:number;excerpt:string};
export type ImportedResult = {conversationId:string;title:string;projectId:string|null;provider:string;messageCount:number};
type Props = {
  currentProject:Project|null;projects:Project[];
  onImported:(items:ImportedResult[],projectId:string|null)=>Promise<void>;
  onClose:()=>void;
};

export default function ImportPanel({currentProject,projects,onImported,onClose}:Props){
  const [provider,setProvider]=useState<Format>("chatgpt");
  const [content,setContent]=useState("");
  const [fileName,setFileName]=useState("");
  const [target,setTarget]=useState(currentProject?.id||"");
  const [previews,setPreviews]=useState<Preview[]>([]);
  const [selected,setSelected]=useState<number[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [result,setResult]=useState("");

  async function loadFile(e:ChangeEvent<HTMLInputElement>){
    const file=e.target.files?.[0];
    if(!file)return;
    setPreviews([]);setSelected([]);setError("");setResult("");
    if(file.size>8_000_000){
      setError("현재는 최대 8MB 파일만 지원합니다. 내보내기 파일을 나누어 주세요.");
      return;
    }
    try{
      setContent(await file.text());
      setFileName(file.name);
    }catch(err){setError(String(err));}
  }

  async function preview(e:FormEvent){
    e.preventDefault();
    setBusy(true);setError("");setResult("");
    try{
      const data=await post<{items:Preview[]}>("/v1/imports/preview",{provider,content});
      setPreviews(data.items);
      // Import requires an explicit conversation selection after preview.
      setSelected([]);
      if(!data.items.length)setError("가져올 수 있는 텍스트 대화가 없습니다.");
    }catch(err){
      setPreviews([]);setSelected([]);
      setError(err instanceof Error?err.message:String(err));
    }finally{setBusy(false);}
  }
  function toggle(index:number){
    setSelected(old=>old.includes(index)?old.filter(x=>x!==index):
      old.length>=20?old:[...old,index]);
  }
  async function commit(){
    if(!selected.length||busy)return;
    setBusy(true);setError("");
    try{
      const data=await post<{
        imported:ImportedResult[];skipped:{index:number;reason:string}[]
      }>("/v1/imports/commit",{
        provider,content,selectedIndexes:selected,projectId:target||null
      });
      setResult(`새 대화 ${data.imported.length}개 저장 · 중복/제외 ${data.skipped.length}개`);
      await onImported(data.imported,target||null);
      setSelected([]);
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  }

  return <aside className="import-panel">
    <div className="memory-header">
      <div><UploadCloud size={19}/><strong>AI 대화 가져오기</strong></div>
      <button className="icon-button" onClick={onClose} aria-label="가져오기 닫기"><X size={17}/></button>
    </div>
    <div className="import-scroll">
      <p className="memory-intro">기존 AI 대화를 Gleave 프로젝트에 연결할 수 있습니다. 가져온 대화는 확인 후에만 프로젝트 기억으로 승인됩니다.</p>
      <form className="codex-section" onSubmit={e=>void preview(e)}>
        <label className="codex-label" htmlFor="import-provider"><FileJson size={16}/> 원본 서비스</label>
        <select id="import-provider" value={provider} onChange={e=>{
          setProvider(e.target.value as Format);setPreviews([]);setSelected([]);
        }} className="import-select">
          <option value="chatgpt">ChatGPT 대화 내보내기 (conversations.json)</option>
          <option value="claude">Claude 대화 내보내기 (conversations.json)</option>
          <option value="codex">Codex CLI 세션 (.jsonl)</option>
        </select>
        <label className="import-file">
          <UploadCloud size={17}/>
          <span>{fileName||"JSON / JSONL 파일 선택"}</span>
          <input type="file" accept=".json,.jsonl,application/json" onChange={e=>void loadFile(e)}/>
        </label>
        <p className="codex-hint">최대 8MB · 텍스트 대화만 지원 · 시스템 명령/도구 출력/미디어는 가져오지 않습니다.</p>
        <label htmlFor="import-project" className="codex-label"><Folder size={15}/> 대화를 묶을 프로젝트</label>
        <select id="import-project" value={target} onChange={e=>setTarget(e.target.value)} className="import-select">
          <option value="">프로젝트 외 대화</option>
          {projects.map(project=><option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <button type="submit" disabled={!content||busy} className="codex-run">대화 미리보기</button>
      </form>
      {error&&<div className="codex-error" role="alert">{error}</div>}
      {result&&<div className="import-success" role="status">{result}</div>}
      {previews.length>0&&<section className="codex-section">
        <div className="codex-label">가져올 대화 선택 ({selected.length}/20)</div>
        <div className="import-select-actions">
          <button type="button" onClick={()=>setSelected(previews.slice(0,20).map(p=>p.index))}>처음 20개 선택</button>
          <button type="button" onClick={()=>setSelected([])}>선택 해제</button>
        </div>
        <p className="codex-hint">선택한 대화만 저장합니다. 기존 기록은 출처 ID로 중복 확인합니다.</p>
        <div className="import-results">{previews.map(item=><label key={item.index} className="import-item">
          <input type="checkbox" checked={selected.includes(item.index)} onChange={()=>toggle(item.index)}/>
          <span><strong>{item.title}</strong><small>{item.messageCount}개 메시지 · {item.excerpt||"텍스트 미리보기 없음"}</small></span>
        </label>)}</div>
        <button className="codex-run" disabled={!selected.length||busy} onClick={()=>void commit()}>
          선택한 {selected.length}개 대화 가져오기
        </button>
      </section>}
      <p className="codex-hint import-policy">가져온 텍스트를 현재 채팅에서 열거나 이어서 질문하면 선택한 AI 공급자에게 전송될 수 있습니다. 다른 채팅의 자동 참고 자료나 개인 LLM의 학습 데이터로는 자동 등록되지 않습니다.</p>
    </div>
  </aside>;
}
