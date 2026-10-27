export type Workspace = {id:string;name:string;kind:"personal"|"team";owner_user_id:string;role:string};
export type Project = {id:string;workspace_id:string;name:string};
export type Conversation = {id:string;title:string;user_id:string;projectId?:string};
export type Message = {id:string;role:"user"|"assistant"|"tool"|"system";content:string;status:string;provider?:string|null;model?:string|null};
export type ProjectMemory = {id:string;project_id:string;content:string;status:string};
export type ServerEvent = {eventId:string;requestId:string;sequence:number;eventType:string;payload:Record<string,unknown>};
export type RuntimeStatus = {conversationProvider?:{name:string;status:string;model?:string|null};providers?:Record<string,{status:string}>};

export async function request<T>(path:string, init:RequestInit = {}):Promise<T> {
  const headers: Record<string,string> = {"Content-Type":"application/json", ...(init.headers as Record<string,string>||{})};
  const response = await fetch(path,{...init,headers});
  if (!response.ok){
    let detail = "";
    try { const err=await response.json();detail=typeof err.detail==="string"?err.detail:JSON.stringify(err.detail||err); }
    catch { detail=response.statusText; }
    throw new Error(`요청 실패 (${response.status}): ${detail}`);
  }
  return response.json() as Promise<T>;
}
export const get = <T,>(url:string)=>request<T>(url);
export const post = <T,>(url:string, body:unknown)=>request<T>(url,{method:"POST",body:JSON.stringify(body)});
export const put = <T,>(url:string)=>request<T>(url,{method:"PUT"});
export const del = <T,>(url:string)=>request<T>(url,{method:"DELETE"});
