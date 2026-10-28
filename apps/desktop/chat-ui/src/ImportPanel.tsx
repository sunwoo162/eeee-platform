import { ChangeEvent, FormEvent, useState } from "react";
import { FileArchive, Folder, UploadCloud, X } from "lucide-react";
import { Project, post } from "./api";

type Format = "chatgpt"|"claude"|"codex";
type Preview = {index:number;provider:string;title:string;messageCount:number;excerpt:string};
type StagePage = {sessionId:string;total:number;offset:number;items:Preview[]};
export type ImportedResult = {
  conversationId:string;title:string;projectId:string|null;provider:string;messageCount:number;
};
type Props = {
  currentProject:Project|null;projects:Project[];
  onImported:(items:ImportedResult[],projectId:string|null)=>Promise<void>;
  onClose:()=>void;
};

export default function ImportPanel({currentProject,projects,onImported,onClose}:Props){
  const [provider,setProvider]=useState<Format>("chatgpt");
  const [file,setFile]=useState<File|null>(null);
  const [target,setTarget]=useState(currentProject?.id||"");
  const [page,setPage]=useState<StagePage|null>(null);
  const [selected,setSelected]=useState<number[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [result,setResult]=useState("");

  function reset(fileValue:File|null){
    setFile(fileValue);
    setPage(null);setSelected([]);setError("");setResult("");
  }
  function loadFile(e:ChangeEvent<HTMLInputElement>){
    const picked=e.target.files?.[0]||null;
    reset(picked);
    if(picked && picked.size>64_000_000){
      setFile(null);
      setError("64MB 이하 JSON, JSONL 또는 ZIP 파일만 지원합니다.");
    }
  }
  async function getPage(sessionId:string,offset:number){
    const response=await fetch(`/v1/imports/sessions/${sessionId}?offset=${offset}&limit=40`);
    if(!response.ok)throw new Error(`페이지 조회 실패 (${response.status})`);
    setPage(await response.json() as StagePage);
  }
  async function preview(e:FormEvent){
    e.preventDefault();
    if(!file || busy)return;
    setBusy(true);setError("");setResult("");setSelected([]);
    try{
      const path=`/v1/imports/upload?provider=${encodeURIComponent(provider)}&filename=${encodeURIComponent(file.name)}`;
      const response=await fetch(path,{
        method:"POST",body:file,headers:{"Content-Type":"application/octet-stream"},
      });
      const data=await response.json();
      if(!response.ok)throw new Error(String(data.detail||"파일 분석 실패"));
      const loaded=data as StagePage;
      setPage(loaded);
      if(!loaded.total)setError("텍스트 대화가 발견되지 않았습니다.");
    }catch(err){
      setPage(null);setError(err instanceof Error?err.message:String(err));
    }finally{setBusy(false);}
  }
  function toggle(index:number){
    setSelected(old=>old.includes(index)?old.filter(x=>x!==index):
      old.length>=20?old:[...old,index]);
  }
  async function commit(){
    if(!page || !selected.length || busy)return;
    setBusy(true);setError("");
    try{
      const data=await post<{
        imported:ImportedResult[];skipped:{index:number;reason:string}[];
      }>(`/v1/imports/sessions/${page.sessionId}/commit`,{
        selectedIndexes:selected,projectId:target||null,
      });
      setResult(`새 대화 ${data.imported.length}개 · 중복/제외 ${data.skipped.length}개`);
      setSelected([]);
      await onImported(data.imported,target||null);
    }catch(err){
      setError(err instanceof Error?err.message:String(err));
    }finally{setBusy(false);}
  }
  return <aside className="import-panel">
    <div className="memory-header">
      <div><UploadCloud size={19}/><strong>AI 대화 가져오기</strong></div>
      <button className="icon-button" onClick={onClose} aria-label="가져오기 닫기"><X size={17}/></button>
    </div>
    <div className="import-scroll">
      <p className="memory-intro">다른 AI의 내보내기 파일을 Gleave 채팅으로 불러옵니다. 승인 전에는 프로젝트 기억이나 학습 데이터로 사용하지 않습니다.</p>
      <form className="codex-section" onSubmit={e=>void preview(e)}>
        <label className="codex-label" htmlFor="import-provider"><FileArchive size={16}/> 원본 서비스</label>
        <select id="import-provider" className="import-select" value={provider}
          onChange={e=>{setProvider(e.target.value as Format);reset(null);}}>
          <option value="chatgpt">ChatGPT 대화 내보내기</option>
          <option value="claude">Claude 대화 내보내기</option>
          <option value="codex">Codex CLI 세션</option>
        </select>
        <label className="import-file">
          <UploadCloud size={17}/><span>{file?.name||"ZIP · JSON · JSONL 파일 선택"}</span>
          <input type="file" accept=".zip,.json,.jsonl,application/zip,application/json"
            onChange={loadFile}/>
        </label>
        <p className="codex-hint">최대 64MB 업로드. ZIP은 서버에서 압축 해제 크기와 안전성을 검사한 후 대화 내용만 읽습니다.</p>
        <label htmlFor="import-project" className="codex-label"><Folder size={15}/> 가져올 프로젝트</label>
        <select id="import-project" className="import-select" value={target}
          onChange={e=>setTarget(e.target.value)}>
          <option value="">프로젝트 외 대화</option>
          {projects.map(project=><option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <button type="submit" className="codex-run" disabled={!file||busy}>
          {busy?"분석 중...":"대화 목록 미리보기"}
        </button>
      </form>
      {error&&<div className="codex-error" role="alert">{error}</div>}
      {result&&<div className="import-success" role="status">{result}</div>}
      {page&&page.total>0&&<section className="codex-section">
        <div className="codex-label">총 {page.total}개 대화 · 선택 {selected.length}/20</div>
        <p className="codex-hint">미리보기는 저장하지 않습니다. 필요한 대화를 체크한 뒤 가져오세요.</p>
        <div className="import-select-actions">
          <button type="button" onClick={()=>setSelected(old=>[
            ...old,...page.items.filter(item=>!old.includes(item.index))
              .slice(0,Math.max(0,20-old.length)).map(item=>item.index)
          ])}>현재 페이지 선택</button>
          <button type="button" onClick={()=>setSelected([])}>선택 해제</button>
        </div>
        <div className="import-results">
          {page.items.map(item=><label key={item.index} className="import-item">
            <input type="checkbox" checked={selected.includes(item.index)}
              onChange={()=>toggle(item.index)}/>
            <span><strong>{item.title}</strong>
              <small>{item.messageCount}개 메시지 · {item.excerpt||"미리보기 없음"}</small>
            </span>
          </label>)}
        </div>
        <div className="import-pages">
          <button disabled={busy||page.offset===0}
            onClick={()=>void getPage(page.sessionId,Math.max(0,page.offset-40)).catch(e=>setError(String(e)))}>
            이전
          </button>
          <span>{Math.floor(page.offset/40)+1} / {Math.ceil(page.total/40)}</span>
          <button disabled={busy||page.offset+40>=page.total}
            onClick={()=>void getPage(page.sessionId,page.offset+40).catch(e=>setError(String(e)))}>
            다음
          </button>
        </div>
        <button className="codex-run" disabled={!selected.length||busy}
          onClick={()=>void commit()}>선택한 {selected.length}개 가져오기</button>
      </section>}
      <p className="codex-hint import-policy">원본은 로컬 Gleave 서버에서만 분석됩니다. 다른 AI로 이어서 질문하면 그 대화가 선택한 공급자에게 전송될 수 있습니다. 저장된 대화는 프로젝트 기억으로 자동 공유되지 않습니다.</p>
    </div>
  </aside>;
}
