import { FormEvent, useEffect, useRef, useState } from "react";
import { Check, CodeXml, FolderOpen, Play, RefreshCcw, ShieldAlert, Square, X } from "lucide-react";
import { Conversation, Project, get, post, put } from "./api";

type Approval = {id:string;method:string;reason:string;command:string};
type AuditEntry = {sequence:number;kind:string;timestamp:string;data:Record<string,unknown>};
type CodexTask = {
  id:string;status:string;mode:string;directory:string;answer:string;diff:string;
  prompt?:string;
  error:string|null;pendingApproval:Approval|null;
  events:Array<{index:number;type:string;text:string}>;
};

interface Props {
  project:Project;
  chat:Conversation|null;
  onCreateChat:()=>Promise<Conversation|null>;
  onTaskCompleted:()=>Promise<void>;
  initialTaskId?:string|null;
  onClose:()=>void;
}

export default function CodexPanel({project,chat,onCreateChat,onTaskCompleted,initialTaskId,onClose}:Props) {
  const [directory,setDirectory] = useState("");
  const [bound,setBound] = useState(false);
  const [prompt,setPrompt] = useState("");
  const [mode,setMode] = useState<"readOnly"|"workspaceWrite">("readOnly");
  const [confirmed,setConfirmed] = useState(false);
  const [task,setTask] = useState<CodexTask|null>(null);
  const [history,setHistory] = useState<CodexTask[]>([]);
  const [audit,setAudit] = useState<AuditEntry[]>([]);
  const completedRef=useRef<Set<string>>(new Set());
  const [working,setWorking] = useState(false);
  const [error,setError] = useState("");
  const active = task && ["queued","running","approvalRequired"].includes(task.status);

  async function loadHistory(conversationId:string){
    const response=await get<{items:CodexTask[]}>(`/v1/conversations/${conversationId}/codex/tasks`);
    setHistory(response.items);
    return response.items;
  }

  async function loadDirectory() {
    const result = await get<{directory:{relativePath:string}|null}>(
      `/v1/projects/${project.id}/codex/directory`
    );
    setDirectory(result.directory?.relativePath||"");
    setBound(Boolean(result.directory));
  }

  useEffect(()=>{
    void loadDirectory().catch(e=>setError(String(e)));
    // Each project mounts a different panel (key={project.id}).
  },[project.id]);

  useEffect(()=>{
    if(!initialTaskId)return;
    void get<CodexTask>(`/v1/codex/tasks/${initialTaskId}`).then(setTask)
      .catch(e=>setError(String(e)));
  },[initialTaskId]);

  useEffect(()=>{
    if(!chat?.id)return;
    void loadHistory(chat.id).then(items=>{
      if(!initialTaskId)setTask(items[0]??null);
    }).catch(e=>setError(String(e)));
  },[chat?.id,initialTaskId]);

  useEffect(()=>{
    if(!task?.id){setAudit([]);return;}
    void get<{items:AuditEntry[]}>(`/v1/codex/tasks/${task.id}/audit`)
      .then(r=>setAudit(r.items))
      .catch(e=>setError(String(e)));
  },[task?.id,task?.status]);

  useEffect(()=>{
    if(!task?.id||active||completedRef.current.has(task.id))return;
    if(!task.events.some(e=>e.type==="chatSaved"))return;
    completedRef.current.add(task.id);
    void onTaskCompleted();
    if(chat?.id)void loadHistory(chat.id).catch(e=>setError(String(e)));
  },[task?.id,task?.status,active,chat?.id]);

  useEffect(()=>{
    if(!task?.id||!active)return;
    const timer=window.setInterval(()=>{
      void get<CodexTask>(`/v1/codex/tasks/${task.id}`).then(setTask)
        .catch(e=>setError(String(e)));
    },1200);
    return ()=>window.clearInterval(timer);
  },[task?.id,active]);

  async function bindDirectory(e:FormEvent) {
    e.preventDefault();
    setWorking(true);setError("");
    try{
      await putDirectory();
      await loadDirectory();
    }catch(e){setError(String(e));}
    finally{setWorking(false);}
  }
  async function createManagedDirectory(){
    setWorking(true);setError("");
    try{
      await post(`/v1/projects/${project.id}/codex/directory/create`,{});
      await loadDirectory();
    }catch(e){setError(String(e));}
    finally{setWorking(false);}
  }
  async function putDirectory() {
    await fetchJson(`/v1/projects/${project.id}/codex/directory`,{
      method:"PUT", body:JSON.stringify({relativePath:directory})
    });
  }
  async function submit(e:FormEvent) {
    e.preventDefault();
    if(!prompt.trim()||!bound||working||active)return;
    setWorking(true);setError("");
    try{
      let currentChat=chat;
      if(!currentChat)currentChat=await onCreateChat();
      if(!currentChat)throw new Error("채팅을 먼저 생성해야 합니다.");
      const created=await post<CodexTask>(
        `/v1/projects/${project.id}/codex/tasks`,
        {
          conversationId:currentChat.id,
          prompt:prompt.trim(),mode,
          approvedWorkspaceWrite: mode==="workspaceWrite"&&confirmed
        }
      );
      setTask(created);
      await loadHistory(currentChat.id);
    }catch(e){setError(String(e));}
    finally{setWorking(false);}
  }
  async function decide(decision:"accept"|"decline") {
    if(!task?.pendingApproval)return;
    setWorking(true);setError("");
    try{
      await post(`/v1/codex/tasks/${task.id}/approval`,{
        approvalId:task.pendingApproval.id,decision
      });
      setTask(await get<CodexTask>(`/v1/codex/tasks/${task.id}`));
    }catch(e){setError(String(e));}
    finally{setWorking(false);}
  }
  async function cancel() {
    if(!task)return;
    setWorking(true);setError("");
    try{
      await post(`/v1/codex/tasks/${task.id}/cancel`,{});
      setTask(await get<CodexTask>(`/v1/codex/tasks/${task.id}`));
    }catch(e){setError(String(e));}
    finally{setWorking(false);}
  }

  return <aside className="codex-panel">
    <div className="memory-header">
      <div><CodeXml size={19}/><strong>Codex 개발 작업</strong></div>
      <button className="icon-button" onClick={onClose} aria-label="닫기"><X size={17}/></button>
    </div>
    <div className="codex-scroll">
      <p className="memory-intro">선택한 프로젝트 폴더의 코드를 분석하고, 승인된 범위에서 개발 작업을 실행합니다.</p>
      <div className="codex-section">
        <div className="codex-label"><FolderOpen size={15}/> 작업 폴더</div>
        <form onSubmit={e=>void bindDirectory(e)} className="codex-bind">
          <input aria-label="작업 디렉터리 상대 경로" placeholder="예: projects/my-app"
            value={directory} onChange={e=>{setDirectory(e.target.value);setBound(false);}}/>
          <button type="submit" disabled={working||!directory.trim()}>연결</button>
        </form>
        <p className="codex-hint">EEEE_WORKSPACE_ROOT 내부에 이미 존재하는 폴더의 상대 경로만 지정할 수 있습니다.</p>
        {!bound&&<button type="button" className="codex-managed" disabled={working}
          onClick={()=>void createManagedDirectory()}>비어 있는 전용 작업 폴더 만들기</button>}
        <div className={bound?"codex-ok":"codex-hint"}>{bound?"연결된 로컬 작업 폴더":"작업 폴더가 연결되지 않았습니다."}</div>
      </div>
      <form className="codex-section" onSubmit={e=>void submit(e)}>
        <div className="codex-label"><CodeXml size={15}/> Codex에게 작업 요청</div>
        <textarea className="codex-prompt" value={prompt} rows={4}
          placeholder="예: 이 프로젝트의 테스트 실패 원인을 조사해줘."
          onChange={e=>setPrompt(e.target.value)}/>
        <div className="codex-modes">
          <label><input type="radio" name="codex-mode" value="readOnly"
            checked={mode==="readOnly"} onChange={()=>{setMode("readOnly");setConfirmed(false);}}/> 분석만</label>
          <label><input type="radio" name="codex-mode" value="workspaceWrite"
            checked={mode==="workspaceWrite"} onChange={()=>setMode("workspaceWrite")}/> 파일 수정 허용</label>
        </div>
        {mode==="workspaceWrite"&&<label className="codex-consent">
          <input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
          <span>Codex가 연결된 프로젝트 내부 파일을 수정할 수 있음을 이해합니다. 추가 권한 요청은 별도로 확인합니다.</span>
        </label>}
        <button type="submit" className="codex-run" disabled={!bound||!prompt.trim()||working||Boolean(active)||(mode==="workspaceWrite"&&!confirmed)}>
          <Play size={15}/>{mode==="readOnly"?"코드 분석 시작":"승인하고 작업 시작"}
        </button>
      </form>
      {error&&<div role="alert" className="codex-error">{error}</div>}
      {history.length>0&&<details className="codex-section codex-history">
        <summary>이 채팅의 Codex 작업 기록 ({history.length})</summary>
        <div className="codex-history-list">{history.map(item=><button key={item.id}
          className={task?.id===item.id?"codex-history-item chosen":"codex-history-item"}
          onClick={()=>void get<CodexTask>(`/v1/codex/tasks/${item.id}`).then(setTask)
            .catch(e=>setError(String(e)))}>
          <span>{(item.prompt||"Codex 작업").slice(0,65)}</span>
          <small>{item.mode==="workspaceWrite"?"파일 수정":"읽기 전용"} · {item.status}</small>
        </button>)}</div>
      </details>}
      {task&&<div className="codex-section codex-result">
        <div className="codex-label">
          <RefreshCcw size={15}/> 작업 상태: <strong>{task.status}</strong>
        </div>
        {active&&<button className="codex-cancel" onClick={()=>void cancel()} disabled={working}>
          <Square size={13}/> 작업 취소
        </button>}
        {task.pendingApproval&&<div className="codex-approval">
          <div className="codex-label"><ShieldAlert size={17}/> 추가 권한 승인 필요</div>
          <p>{task.pendingApproval.reason||task.pendingApproval.method}</p>
          {task.pendingApproval.command&&<pre>{task.pendingApproval.command}</pre>}
          <div className="codex-approval-buttons">
            <button onClick={()=>void decide("decline")} disabled={working}>거절</button>
            <button onClick={()=>void decide("accept")} disabled={working}><Check size={14}/> 허용</button>
          </div>
        </div>}
        {!active&&<button className="codex-managed" onClick={()=>void onTaskCompleted()}>
          이 채팅에서 Codex 결과 보기
        </button>}
        {task.error&&<p className="codex-error">{task.error}</p>}
        {task.answer&&<div className="codex-output">
          <strong>Codex 결과</strong><p>{task.answer}</p>
        </div>}
        {task.diff&&<div className="codex-output">
          <strong>코드 변경 사항</strong><pre>{task.diff}</pre>
        </div>}
        <div className="codex-events">{task.events.slice(-15).map(event=>
          <p key={event.index}><span>{event.type}</span> {event.text}</p>
        )}</div>
        {audit.length>0&&<details className="codex-audit">
          <summary>저장된 작업·승인 감사 기록 ({audit.length})</summary>
          {audit.map(entry=><div key={entry.sequence} className="codex-audit-entry">
            <strong>{entry.kind}</strong>
            <time>{new Date(entry.timestamp).toLocaleString("ko-KR")}</time>
            <pre>{JSON.stringify(entry.data,null,2)}</pre>
          </div>)}
        </details>}
        <p className="codex-hint">Codex로 전달한 요청·소스 파일은 연결된 AI 서비스에서 처리될 수 있습니다. 작업 상태·로그·승인 기록은 로컬 DB에 보관되며, 중단된 프로세스는 자동 재실행되지 않습니다.</p>
      </div>}
    </div>
  </aside>;
}

async function fetchJson(path:string,options:RequestInit):Promise<unknown>{
  const res=await fetch(path,{
    ...options,
    headers:{"Content-Type":"application/json"},
  });
  if(!res.ok){
    const data=await res.json().catch(()=>({detail:res.statusText}));
    throw new Error(typeof data.detail==="string"?data.detail:"작업 폴더 연결 실패");
  }
  return res.json();
}
