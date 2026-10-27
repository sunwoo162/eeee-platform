import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  ArrowDown, ArrowUp, BrainCircuit, ChevronDown, ChevronRight, CirclePlus, CodeXml,
  Folder, FolderOpen, Layers3, Menu, MessageSquare, MoreHorizontal,
  PanelRight, Plus, Search, Settings2, Sparkles, SquarePen, Trash2, UploadCloud, Users, UserRound,
  X
} from "lucide-react";
import { Conversation, Message, Project, ProjectMemory, ProviderOption, RuntimeStatus, ServerEvent, Workspace, del, get, post, put } from "./api";
import CodexPanel from "./CodexPanel";
import ImportPanel, {ImportedResult} from "./ImportPanel";

type EditKind = {kind:"workspace"|"project"; workspaceId?:string}|null;
const terminal = new Set(["message.completed","request.failed","request.cancelled"]);
const titleFor = (kind:string) => kind==="team"?"팀 공간":"개인 공간";

export default function App() {
  const [workspaces,setWorkspaces] = useState<Workspace[]>([]);
  const [projects,setProjects] = useState<Record<string,Project[]>>({});
  const [projectChats,setProjectChats] = useState<Record<string,Conversation[]>>({});
  const [allChats,setAllChats] = useState<Conversation[]>([]);
  const [selectedProject,setSelectedProject] = useState<Project|null>(null);
  const [selectedChat,setSelectedChat] = useState<Conversation|null>(null);
  const [messages,setMessages] = useState<Message[]>([]);
  const [runtime,setRuntime] = useState<RuntimeStatus|null>(null);
  const [providerMode,setProviderMode] = useState("auto");
  const [providers,setProviders] = useState<ProviderOption[]>([]);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [draft,setDraft] = useState("");
  const [expanded,setExpanded] = useState<Record<string,boolean>>({});
  const [editor,setEditor] = useState<EditKind>(null);
  const [entryName,setEntryName] = useState("");
  const [workspaceKind,setWorkspaceKind] = useState<"personal"|"team">("personal");
  const [memoryOpen,setMemoryOpen] = useState(false);
  const [devOpen,setDevOpen] = useState(false);
  const [importOpen,setImportOpen] = useState(false);
  const [activeCodexTaskId,setActiveCodexTaskId] = useState<string|null>(null);
  const [memories,setMemories] = useState<ProjectMemory[]>([]);
  const [memoryDraft,setMemoryDraft] = useState("");
  const [mobileSidebar,setMobileSidebar] = useState(false);
  const messagesEnd=useRef<HTMLDivElement|null>(null);
  const sourceRef=useRef<EventSource|null>(null);
  const activeRequestRef=useRef<string|null>(null);
  const currentChatId=useRef<string|null>(null);

  async function refreshTree() {
    const [spaces,history] = await Promise.all([
      get<{items:Workspace[]}>("/v1/workspaces"),
      get<{items:Conversation[]}>("/v1/conversations?limit=100")
    ]);
    const nextProjects:Record<string,Project[]> = {};
    const nextChats:Record<string,Conversation[]> = {};
    await Promise.all(spaces.items.map(async w=>{
      const result=await get<{items:Project[]}>(`/v1/workspaces/${w.id}/projects`);
      nextProjects[w.id]=result.items;
      await Promise.all(result.items.map(async p=>{
        const chats=await get<{items:Conversation[]}>(`/v1/projects/${p.id}/conversations`);
        nextChats[p.id]=chats.items;
      }));
    }));
    setWorkspaces(spaces.items);
    setAllChats(history.items);
    setProjects(nextProjects);
    setProjectChats(nextChats);
  }

  useEffect(()=>{
    void Promise.all([
      refreshTree(),
      get<RuntimeStatus>("/v1/runtime").then(setRuntime),
      get<{items:ProviderOption[]}>("/v1/providers").then(r=>setProviders(r.items)),
    ])
      .catch(e=>setError(e instanceof Error?e.message:String(e)));
    return ()=>sourceRef.current?.close();
  },[]);
  useEffect(()=>{messagesEnd.current?.scrollIntoView({behavior:"smooth",block:"end"});},[messages,busy]);

  async function chooseChat(chat:Conversation, project:Project|null) {
    sourceRef.current?.close();
    currentChatId.current=chat.id;
    setActiveCodexTaskId(null);
    setSelectedChat(chat);
    setProviderMode(sessionStorage.getItem("gleave-provider:"+chat.id)||"auto");
    setSelectedProject(project);
    setMobileSidebar(false);
    setBusy(false);
    setError("");
    try {const result=await get<{items:Message[]}>(`/v1/conversations/${chat.id}/messages?limit=500`);
      if(currentChatId.current===chat.id)setMessages(result.items);}
    catch(e){setError(String(e));}
  }
  function chooseProject(project:Project){
    sourceRef.current?.close();
    currentChatId.current=null;
    setActiveCodexTaskId(null);
    setSelectedProject(project);setSelectedChat(null);setMessages([]);
    setExpanded(old=>({...old,[project.id]:true}));setMobileSidebar(false);setBusy(false);
  }
  async function createChat(){
    setError("");
    try {
      const chat = selectedProject
        ?await post<Conversation>(`/v1/projects/${selectedProject.id}/conversations`,{title:"새 대화"})
        :await post<Conversation>("/v1/conversations",{title:"새 대화"});
      await refreshTree();
      await chooseChat(chat,selectedProject);
      return chat;
    } catch(e) {setError(String(e));return null;}
  }
  async function moveChatToProject(conversationId:string,project:Project){
    try{
      await put(`/v1/projects/${project.id}/conversations/${conversationId}`);
      await refreshTree();
      if(currentChatId.current===conversationId)setSelectedProject(project);
      setError("");
    }catch(err){setError(err instanceof Error?err.message:String(err));}
  }
  async function unassignChat(conversationId:string){
    try{
      await del(`/v1/conversations/${conversationId}/project`);
      await refreshTree();
      if(currentChatId.current===conversationId)setSelectedProject(null);
      setError("");
    }catch(err){setError(err instanceof Error?err.message:String(err));}
  }
  async function createFolder(e:FormEvent){
    e.preventDefault();
    try {
      if(!entryName.trim())return;
      if(editor?.kind==="workspace"){
        await post("/v1/workspaces",{name:entryName.trim(),kind:workspaceKind});
      } else if(editor?.kind==="project"&&editor.workspaceId){
        await post(`/v1/workspaces/${editor.workspaceId}/projects`,{name:entryName.trim()});
        setExpanded(o=>({...o,[editor.workspaceId!]:true}));
      }
      setEntryName("");setEditor(null);await refreshTree();
    }catch(err){setError(String(err));}
  }
  async function refreshCurrentChat(){
    const id=currentChatId.current;
    if(!id)return;
    try{
      const result=await get<{items:Message[]}>(`/v1/conversations/${id}/messages?limit=500`);
      if(currentChatId.current===id)setMessages(result.items);
    }catch(e){setError(String(e));}
  }
  async function onImported(items:ImportedResult[],projectId:string|null){
    await refreshTree();
    if(items.length){
      const project=Object.values(projects).flat().find(p=>p.id===projectId)||null;
      await chooseChat({
        id:items[0].conversationId,title:items[0].title,user_id:"local-user"
      },project);
      setImportOpen(false);
    }
  }
  async function approveImportedMemory(message:Message){
    if(!selectedProject||message.role!=="user"||!message.provider?.startsWith("import:"))return;
    if(!window.confirm("선택한 메시지를 이 프로젝트의 승인된 기억으로 추가할까요? 팀 프로젝트라면 팀의 AI에게도 제공될 수 있습니다."))return;
    try{
      await post(`/v1/projects/${selectedProject.id}/memories`,{
        content:message.content.slice(0,2000),source_message_id:message.id
      });
      setMemoryOpen(true);
      setImportOpen(false);
      setDevOpen(false);
      await loadMemories();
      setError("");
    }catch(err){setError(err instanceof Error?err.message:String(err));}
  }
  async function loadMemories(){
    if(!selectedProject)return;
    try {const result=await get<{items:ProjectMemory[]}>(`/v1/projects/${selectedProject.id}/memories`);setMemories(result.items);}
    catch(e){setError(String(e));}
  }
  async function addMemory(e:FormEvent){
    e.preventDefault();
    if(!selectedProject||!memoryDraft.trim())return;
    try {
      await post(`/v1/projects/${selectedProject.id}/memories`,{content:memoryDraft.trim()});
      setMemoryDraft("");await loadMemories();
    }catch(e){setError(String(e));}
  }
  async function removeMemory(id:string){
    if(!selectedProject)return;
    try {await del(`/v1/projects/${selectedProject.id}/memories/${id}`);await loadMemories();}
    catch(e){setError(String(e));}
  }
  async function send(e?:FormEvent){
    e?.preventDefault();
    if(!draft.trim()||busy)return;
    if(providerMode==="codex"&&!selectedProject){
      setError("Codex는 프로젝트 채팅에서만 실행할 수 있습니다.");
      return;
    }
    let chat=selectedChat;
    if(!chat){chat=await createChat();if(!chat)return;}
    const message=draft.trim();
    const id=chat.id;
    if(providerMode==="codex"){
      if(!selectedProject){
        setError("Codex는 프로젝트 채팅에서만 실행할 수 있습니다.");
        return;
      }
      setBusy(true);setError("");
      try{
        const result=await post<{id:string}>(
          `/v1/projects/${selectedProject.id}/codex/tasks`,{
            conversationId:id,prompt:message,mode:"readOnly",
          }
        );
        setDraft("");
        setActiveCodexTaskId(result.id);
        setDevOpen(true);setMemoryOpen(false);
        setMessages(items=>[...items,{
          id:`codex-pending-${result.id}`,role:"user",
          content:message,status:"pending",
        }]);
      }catch(err){
        setDevOpen(true);setMemoryOpen(false);
        setError(err instanceof Error?err.message:String(err));
      }finally{setBusy(false);}
      return;
    }
    setDraft("");setBusy(true);setError("");
    currentChatId.current=id;
    setMessages(items=>[...items,{id:`local-${crypto.randomUUID()}`,role:"user",content:message,status:"completed"}]);
    try {
      const result=await post<{requestId:string}>(`/v1/conversations/${id}/turns`,{
        clientMessageId:crypto.randomUUID(),content:message,provider:providerMode
      });
      sourceRef.current?.close();
      activeRequestRef.current=result.requestId;
      const streamId=`pending-${result.requestId}`;
      const seen=new Set<string>();
      const source=new EventSource(`/v1/requests/${result.requestId}/events?timeoutSeconds=30`);
      sourceRef.current=source;
      source.onmessage=(event:MessageEvent<string>)=>{
        if(currentChatId.current!==id){source.close();return;}
        let data:ServerEvent;
        try{data=JSON.parse(event.data) as ServerEvent;}catch{return;}
        if(seen.has(data.eventId))return;
        seen.add(data.eventId);
        if(data.eventType==="message.delta"){
          const delta=typeof data.payload.delta==="string"?data.payload.delta:"";
          setMessages(items=>{
            const idx=items.findIndex(item=>item.id===streamId);
            if(idx<0)return [...items,{id:streamId,role:"assistant",content:delta,status:"streaming"}];
            return items.map((item,i)=>i===idx?{...item,content:item.content+delta}:item);
          });
        }
        if(terminal.has(data.eventType)){
          source.close();setBusy(false);
          if(activeRequestRef.current===result.requestId)activeRequestRef.current=null;
          if(data.eventType!=="message.completed")setError(
            typeof data.payload.message==="string"?data.payload.message:"AI 응답이 완료되지 않았습니다."
          );
          void get<{items:Message[]}>(`/v1/conversations/${id}/messages?limit=500`)
            .then(response=>{if(currentChatId.current===id)setMessages(response.items);})
            .catch(err=>setError(String(err)));
          void refreshTree();
        }
      };
      source.onerror=()=>{
        // EventSource reconnects. Dedupe eventId so reconnects never repeat delta.
        if(source.readyState===EventSource.CLOSED){
          setBusy(false);setError("연결이 끊겼습니다. 저장된 대화를 다시 열어 확인해 주세요.");
        }
      };
    }catch(err){setBusy(false);setError(err instanceof Error?err.message:String(err));}
  }
  async function cancelTurn(){
    const requestId=activeRequestRef.current;
    if(!requestId)return;
    try{
      await post(`/v1/requests/${requestId}/cancel`,{});
      sourceRef.current?.close();
      activeRequestRef.current=null;
      setBusy(false);
      if(currentChatId.current){
        const chatId=currentChatId.current;
        const result=await get<{items:Message[]}>(`/v1/conversations/${chatId}/messages?limit=500`);
        if(currentChatId.current===chatId)setMessages(result.items);
      }
    }catch(err){setError(err instanceof Error?err.message:String(err));}
  }
  const linked=new Set(Object.values(projectChats).flat().map(c=>c.id));
  const unassigned=allChats.filter(c=>!linked.has(c.id));
  const currentProvider=runtime?.conversationProvider;
  const providerLabel=providers.find(item=>item.id===providerMode)?.label||"Auto";
  function chooseProvider(value:string){
    setProviderMode(value);
    if(selectedChat)sessionStorage.setItem("gleave-provider:"+selectedChat.id,value);
  }

  return <div className="shell">
    <aside className={`sidebar ${mobileSidebar?"sidebar-open":""}`}>
      <div className="brand"><div className="brand-symbol"><Layers3 size={19}/></div><span>Gleave</span>
        <button className="icon-button mobile-only" onClick={()=>setMobileSidebar(false)} aria-label="메뉴 닫기"><X size={18}/></button>
      </div>
      <button className="new-chat" onClick={()=>void createChat()}><SquarePen size={17}/>새 채팅<Plus size={15} className="new-chat-plus"/></button>
      <div className="search-row"><Search size={17}/><span>프로젝트 및 대화</span></div>
      <div className="sidebar-scroll">
        {(["personal","team"] as const).map(kind=><section key={kind}>
          <div className="group-title"><span>{kind==="personal"?<UserRound size={16}/>:<Users size={16}/>} {titleFor(kind)}</span>
            <button className="ghost-icon" title="공간 추가" aria-label={`${titleFor(kind)} 만들기`} onClick={()=>{setEditor({kind:"workspace"});setWorkspaceKind(kind);setEntryName("");}}><Plus size={16}/></button>
          </div>
          {workspaces.filter(w=>w.kind===kind).map(w=><div key={w.id}>
            <div className="workspace-label" onClick={()=>setExpanded(old=>({...old,[w.id]:!old[w.id]}))}>
              {expanded[w.id]===false?<ChevronRight size={14}/>:<ChevronDown size={14}/>}
              <span>{w.name}</span>
              <button className="ghost-icon" title="프로젝트 추가" onClick={e=>{e.stopPropagation();setEditor({kind:"project",workspaceId:w.id});setEntryName("");}}><Plus size={15}/></button>
            </div>
            {expanded[w.id]!==false&&(projects[w.id]||[]).map(project=><div key={project.id}>
              <button className={`project-item ${selectedProject?.id===project.id?"selected":""}`} onClick={()=>chooseProject(project)} title="클릭해서 열거나 채팅을 끌어와 이동"
                onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const chatId=e.dataTransfer.getData("application/x-gleave-chat");if(chatId)void moveChatToProject(chatId,project);}}>
                {selectedProject?.id===project.id?<FolderOpen size={15}/>:<Folder size={15}/>}
                <span>{project.name}</span>
                <span className="project-count">{(projectChats[project.id]||[]).length}</span>
              </button>
              {expanded[project.id]!==false&&(projectChats[project.id]||[]).map(chat=><button
                key={chat.id} className={`chat-item ${selectedChat?.id===chat.id?"active":""}`} draggable
                onDragStart={e=>e.dataTransfer.setData("application/x-gleave-chat",chat.id)}
                onClick={()=>void chooseChat(chat,project)}><MessageSquare size={14}/><span>{chat.title}</span></button>)}
            </div>)}
          </div>)}
          {!workspaces.some(w=>w.kind===kind)&&<button className="empty-group" onClick={()=>{setEditor({kind:"workspace"});setWorkspaceKind(kind);}}>+ 공간 만들기</button>}
        </section>)}
        <section onDragOver={e=>e.preventDefault()}
          onDrop={e=>{e.preventDefault();const id=e.dataTransfer.getData("application/x-gleave-chat");if(id)void unassignChat(id);}}>
          <div className="group-title" title="프로젝트에서 채팅을 빼려면 여기로 끌어오세요"><span><MessageSquare size={16}/> 프로젝트 외 대화</span></div>
          {unassigned.slice(0,25).map(chat=><button key={chat.id} className={`chat-item unassigned ${selectedChat?.id===chat.id?"active":""}`} draggable
            onDragStart={e=>e.dataTransfer.setData("application/x-gleave-chat",chat.id)}
            onClick={()=>void chooseChat(chat,null)}><MessageSquare size={14}/><span>{chat.title}</span></button>)}
        </section>
      </div>
      <div className="sidebar-footer"><div className="account-circle">G</div><span>로컬 Gleave</span><Settings2 size={16}/></div>
    </aside>

    <main className="main-panel">
      <header className="topbar">
        <button className="icon-button mobile-only" onClick={()=>setMobileSidebar(true)} aria-label="메뉴 열기"><Menu size={20}/></button>
        <div className="breadcrumbs"><span>Gleave</span>{selectedProject&&<><ChevronRight size={15}/><span>{selectedProject.name}</span></>}
          {selectedChat&&<><ChevronRight size={15}/><strong>{selectedChat.title}</strong></>}</div>
        <div className="top-actions">
          <div className="model-pill" title="모델을 직접 선택하거나 Auto로 돌아갈 수 있습니다."><Sparkles size={15}/>
            <select aria-label="AI 모델 선택" value={providerMode} onChange={e=>chooseProvider(e.target.value)}>
              {providers.length ? providers.map(option=><option key={option.id} value={option.id} disabled={!option.available}>
                {option.label}{option.available?"":" (연결 필요)"}
              </option>):<option value="auto">Auto</option>}
            </select><ChevronDown size={13}/></div>
          <button className="icon-button" title="다른 AI 대화 가져오기" aria-label="AI 대화 가져오기"
            onClick={()=>{setImportOpen(v=>!v);setDevOpen(false);setMemoryOpen(false);}}><UploadCloud size={18}/></button>
          <button className="icon-button" title="Codex 개발 작업" aria-label="Codex 개발 작업" onClick={()=>{setDevOpen(v=>!v);setMemoryOpen(false);}} disabled={!selectedProject}><CodeXml size={18}/></button>
          <button className="icon-button" title="프로젝트 기억" onClick={()=>{setMemoryOpen(v=>!v);setDevOpen(false);void loadMemories();}} disabled={!selectedProject}><BrainCircuit size={18}/></button>
          <button className="icon-button" aria-label="채팅 만들기" title="새 채팅" onClick={()=>void createChat()}><SquarePen size={17}/></button>
        </div>
      </header>
      <div className="context-line">{selectedProject?<><Folder size={13}/> {selectedProject.name} 프로젝트 기억 사용</>:<><Sparkles size={13}/> 일반 대화</>}
        <span className="context-provider">{currentProvider?`응답 모델: ${currentProvider.name} · ${currentProvider.status}`:"연결 확인 중"}</span>
      </div>
      {error&&<div className="error-banner" role="alert"><span>{error}</span><button onClick={()=>setError("")} aria-label="닫기"><X size={16}/></button></div>}
      <div className="conversation-scroll">
        {messages.length===0?<div className="welcome">
          <div className="welcome-symbol"><Sparkles size={27}/></div>
          <h1>{selectedProject?`${selectedProject.name}에서 무엇을 할까요?`:"무엇이든 물어보세요"}</h1>
          <p>{selectedProject?"이 프로젝트의 다른 채팅과 승인된 기억을 참고할 수 있어요.":"일상부터 개발까지, 하나의 대화에서 시작하세요."}</p>
          <div className="quick-asks">{["아이디어 정리해 줘","코드 오류 설명해 줘","오늘 공부 계획 세워 줘"].map(q=><button key={q} onClick={()=>setDraft(q)}>{q}<ArrowDown size={14}/></button>)}</div>
        </div>:<div className="messages">
          {messages.filter(m=>m.role==="user"||m.role==="assistant").map(m=><div key={m.id} className={`message ${m.role}`}>
            {m.role==="assistant"&&<div className="assistant-icon"><Layers3 size={14}/></div>}
            <div className="message-body">{m.content|| (m.status==="streaming"?"생성 중…":"")}
              {selectedProject&&m.role==="user"&&m.provider?.startsWith("import:")&&<button
                className="import-approve-memory" onClick={()=>void approveImportedMemory(m)}>
                이 메시지를 프로젝트 기억으로 승인
              </button>}
              {m.status==="failed"&&<small className="message-status">응답 실패</small>}
              {m.role==="assistant"&&m.provider&&<small className="model-source">{m.provider}{m.model?` · ${m.model}`:""}</small>}
            </div>
          </div>)}
          {busy&&<div className="generating"><span className="pulsing-dot"/>답변을 작성하고 있어요…</div>}
          <div ref={messagesEnd}/>
        </div>}
      </div>
      <div className="composer-area">
        <form className="composer" onSubmit={e=>void send(e)}>
          <textarea value={draft} onChange={e=>setDraft(e.target.value)} rows={2} placeholder="Gleave에게 메시지를 보내세요..."
            onKeyDown={(e:KeyboardEvent<HTMLTextAreaElement>)=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();void send();}}}/>
          <div className="composer-actions"><div className="composer-mode"><Sparkles size={14}/> {providerLabel}</div>
            {busy?<button type="button" onClick={()=>void cancelTurn()} className="send-button" aria-label="응답 보기 중단"><X size={18}/></button>
              :<button className="send-button" type="submit" aria-label="보내기" disabled={!draft.trim()}><ArrowUp size={19}/></button>}
          </div>
        </form>
        <div className="composer-note">Gleave는 잘못된 정보를 제공할 수 있습니다. 중요한 결과는 확인해 주세요.</div>
      </div>
    </main>

    {importOpen&&<ImportPanel
      currentProject={selectedProject} projects={Object.values(projects).flat()}
      onImported={onImported} onClose={()=>setImportOpen(false)} />}
    {devOpen&&selectedProject&&<CodexPanel
      key={selectedProject.id} project={selectedProject} chat={selectedChat}
      onCreateChat={createChat} onTaskCompleted={refreshCurrentChat}
      initialTaskId={activeCodexTaskId}
      onClose={()=>setDevOpen(false)} />}
    {memoryOpen&&selectedProject&&<aside className="memory-panel">
      <div className="memory-header"><div><BrainCircuit size={18}/><strong>프로젝트 기억</strong></div><button className="icon-button" onClick={()=>setMemoryOpen(false)}><X size={18}/></button></div>
      <p className="memory-intro">같은 프로젝트에 속한 채팅에서 공통으로 참고하는 승인된 메모리입니다.</p>
      <form className="memory-form" onSubmit={e=>void addMemory(e)}><textarea placeholder="확정된 프로젝트 결정이나 규칙" value={memoryDraft} onChange={e=>setMemoryDraft(e.target.value)} rows={3}/><button disabled={!memoryDraft.trim()}>기억 추가 <CirclePlus size={14}/></button></form>
      <div className="memory-list">{memories.map(m=><div className="memory-card" key={m.id}><p>{m.content}</p><button onClick={()=>void removeMemory(m.id)} aria-label="기억 철회" title="기억 철회"><Trash2 size={15}/></button></div>)}{memories.length===0&&<div className="memory-empty">아직 승인된 프로젝트 기억이 없습니다.</div>}</div>
    </aside>}
    {editor&&<div className="modal-backdrop" onClick={()=>setEditor(null)}><form className="modal" onSubmit={e=>void createFolder(e)} onClick={e=>e.stopPropagation()}>
      <div className="modal-symbol">{editor.kind==="workspace"?<Layers3 size={22}/>:<Folder size={22}/>}</div>
      <h2>{editor.kind==="workspace"?"새 공간 만들기":"새 프로젝트 만들기"}</h2><p>{editor.kind==="workspace"?"개인 또는 팀 공간으로 프로젝트를 분류할 수 있어요.":"프로젝트의 채팅은 동일한 프로젝트 기억을 참고해요."}</p>
      <input autoFocus value={entryName} onChange={e=>setEntryName(e.target.value)} placeholder={editor.kind==="workspace"?"예: 개인 작업":"예: Gleave"}/>
      <div className="modal-actions"><button type="button" className="modal-cancel" onClick={()=>setEditor(null)}>취소</button><button className="modal-create" disabled={!entryName.trim()}>만들기</button></div>
    </form></div>}
  </div>;
}
