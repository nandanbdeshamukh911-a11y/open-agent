import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import { Archive, ChevronDown, CircleAlert, CircleCheck, Globe2, Layers3, Menu, MessageSquare, Plus, Settings2, ShieldCheck, Wrench, X } from 'lucide-react';
import '@fontsource-variable/inter';
import '@fontsource/instrument-serif';
import Chat from './Chat';
import Browser from './Browser';
import './style.css';
import TaskReview from './TaskReview';
import {Engineering,Verify} from './Engineering';
import ThemePicker from './ThemePicker';

type Item = Record<string, any>;
async function api<T = any>(path:string, method='GET', body?:unknown) {
  const res=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-Open-Agent':'local'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json(); if(!res.ok) throw new Error(data.detail || 'Request failed'); return data as T;
}
const navigation = [
  {name:'Chat', icon:MessageSquare},
  {name:'Workspace', icon:Layers3},
  {name:'Browser', icon:Globe2},
  {name:'Approvals', icon:ShieldCheck},
  {name:'Memory', icon:Archive},
  {name:'Tools', icon:Wrench},
  {name:'Settings', icon:Settings2},
];

const descriptions: Record<string, string> = {
  Workspace:'Plan changes, run checks, and review results.',
  Browser:'Preview a page and inspect how it behaves.',
  Approvals:'Review actions before they run.',
  Memory:'Manage the preferences your agent remembers.',
  Tools:'Explore built-in tools and import skills.',
  Settings:'Manage your model, tools, and workspace preferences.',
};

function App(){
  const [chatVersion,setChatVersion] = useState(0);
  const [mobileNavOpen,setMobileNavOpen] = useState(false);
  const mobileMenu = useRef<HTMLButtonElement>(null);
  const mainContent = useRef<HTMLElement>(null);
  const [historyTarget,setHistoryTarget] = useState<HTMLDivElement|null>(null);
  const [initialHistoryOpen] = useState(() => window.matchMedia('(min-width: 761px)').matches);
  const [tab,setTab]=useState('Chat'), [tasks,setTasks]=useState<Item[]>([]), [task,setTask]=useState<Item|null>(null), [selected,setSelected]=useState<number|null>(null);
  const [approvals,setApprovals]=useState<Item[]>([]), [memories,setMemories]=useState<Item[]>([]), [skills,setSkills]=useState<Item[]>([]), [status,setStatus]=useState<Item>({});
  const [project,setProject]=useState(''), [request,setRequest]=useState(''), [message,setMessage]=useState(''), [memory,setMemory]=useState(''), [url,setUrl]=useState(''), [modelUrl,setModelUrl]=useState('http://127.0.0.1:11434/v1'), [modelName,setModelName]=useState(''), [retries,setRetries]=useState(3), [inspection,setInspection]=useState<Item|null>(null), [error,setError]=useState('');
  async function refresh(){
    try {const [a,b,c,d]=await Promise.all([api('/tasks'),api('/approvals'),api('/memories'),api('/skills')]);setTasks(a);setApprovals(b);setMemories(c);setSkills(d);if(selected) setTask(await api('/tasks/'+selected));}
    catch(e){setError(String(e));}
  }
  async function getStatus(syncForm=true) {
    try {
      const next = await api('/status');
      setStatus(next);
      if (syncForm) {setModelUrl(next.model_url);setModelName(next.model_name);}
    } catch(e) {
      setStatus({runtime_error:String(e)});
      if (syncForm) setError(String(e));
    }
  }
  useEffect(()=>{
    void getStatus();
    const timer = setInterval(()=>void getStatus(false),30000);
    return ()=>clearInterval(timer);
  },[]);
  useEffect(()=>{refresh();const id=setInterval(refresh,2500);return()=>clearInterval(id);},[selected]);
  async function act(fn:()=>Promise<any>){try{setError('');await fn();await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}}
  const [isolated,setIsolated]=useState(false);
  const pending=approvals.filter(a=>a.status==='pending');
  const runtime = status.runtime_error ? 'Runtime offline' : !status.models ? 'Checking model' :
    status.model_name && status.models.includes(status.model_name) ? status.model_name : 'Select a model';
  const modelAvailable = !!status.models?.includes(status.model_name) && !status.runtime_error;
  const StatusIcon = modelAvailable ? CircleCheck : CircleAlert;
  function navigate(page: string) {
    setTab(page);
    setMobileNavOpen(false);
    if (mobileNavOpen) mainContent.current?.focus({preventScroll:true});
  }
  return <div className="app">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={'sidebar'+(mobileNavOpen?' mobile-open':'')} onKeyDown={event=>{
      if(event.key==='Escape' && mobileNavOpen) {setMobileNavOpen(false);mobileMenu.current?.focus();}
    }}>
      <div className="brand"><span className="brand-icon" aria-hidden="true"><Layers3 size={22}/></span><strong>Open Agent</strong></div>
      <button type="button" className="new-chat" onClick={()=>{setChatVersion(version=>version+1);navigate('Chat')}}>
        <Plus size={18} aria-hidden="true"/> New chat
      </button>
      <button type="button" className="icon-button mobile-nav-toggle" ref={mobileMenu} aria-label="Workspace menu"
        aria-expanded={mobileNavOpen} aria-controls="sidebar-links" onClick={()=>setMobileNavOpen(open=>!open)}>
        {mobileNavOpen?<X size={19}/>:<Menu size={19}/>}
      </button>
      <div id="sidebar-links" className="sidebar-links">
      <nav aria-label="Workspace">
        {navigation.map(({name, icon: Icon})=>
          <button type="button" className={'nav'+(tab===name?' active':'')} aria-current={tab===name?'page':undefined}
            onClick={()=>navigate(name)} key={name}>
            <Icon size={17} aria-hidden="true"/>{name}{name==='Approvals'&&pending.length>0&&<b>{pending.length}</b>}
          </button>
        )}
      </nav>
      <details className="sidebar-history" open={initialHistoryOpen}>
        <summary><ChevronDown size={14} aria-hidden="true"/> Recent chats</summary>
        <div ref={setHistoryTarget}/>
      </details>
      </div>
    </aside>
    <main id="main-content" ref={mainContent} tabIndex={-1} className={tab==='Chat'?'chat-page':'app-page'}>
      <header className="top-bar">
        <h1>{tab}</h1>
        <button type="button" className="runtime-control" onClick={()=>navigate('Settings')}
          title={modelAvailable?'Model available on the local runtime':'Open model settings'}>
          <StatusIcon size={16} aria-hidden="true" className={modelAvailable?'available':''}/>
          <span>{runtime}</span>
        </button>
      </header>
      {tab!=='Chat'&&<p className="page-description">{descriptions[tab]}</p>}
      <Chat key={chatVersion} api={api} visible={tab==='Chat'} historyTarget={historyTarget}
        onFocusChat={()=>navigate('Chat')}
        onCode={text=>{setRequest(text);setTab('Workspace')}}/>
  {tab==='Browser'&&<Browser api={api} onCode={text=>{setRequest(text);setTab('Workspace')}}/>}
  {error&&<div className="error" role="alert">{error}<button onClick={()=>setError('')}>×</button></div>}
  {tab==='Workspace'&&<div className="workspace"><section className="main-column"><div className="section-heading"><div><h2>New coding task</h2></div></div><div className="card composer"><label>Project folder<input value={project} onChange={e=>setProject(e.target.value)} placeholder="D:\\Projects\\my-app"/></label><label>Task description<textarea rows={4} value={request} onChange={e=>setRequest(e.target.value)} placeholder="Describe what you want to create or improve…"/></label><label className="check-option"><input type="checkbox" checked={isolated} onChange={e=>setIsolated(e.target.checked)}/>Create a detached Git worktree and checkpoint from clean HEAD</label><div className="composer-foot"><label className="retry">Repair attempts <input type="number" min="0" max="10" value={retries} onChange={e=>setRetries(Number(e.target.value))}/></label><button className="primary" disabled={!project.trim()||!request.trim()} onClick={()=>act(async()=>{const x=await api('/tasks','POST',{project,request,max_retries:retries,isolated});setSelected(x.id);setRequest('');})}>Start task <span>↗</span></button></div></div>
  <div className="section-heading activity-heading"><div><h2>{task?`Task #${task.id}`:'Task activity'}</h2></div>{task&&<span className={'badge '+task.status}>{task.status.replace('_',' ')}</span>}</div>{task?<div className="card activity"><p className="task-request">{task.request}</p><div className="task-path">{task.project}</div><div className="actions">{['running','waiting_approval'].includes(task.status)&&<button onClick={()=>act(()=>api(`/tasks/${task.id}/pause`,'POST'))}>Pause</button>}{['paused','blocked'].includes(task.status)&&<button onClick={()=>act(()=>api(`/tasks/${task.id}/resume`,'POST'))}>Resume</button>}{!['cancelled','completed'].includes(task.status)&&<button onClick={()=>act(()=>api(`/tasks/${task.id}/cancel`,'POST'))}>Cancel</button>}</div>{task.plan&&<div className="plan"><b>PLAN</b><p>{task.plan}</p><b>REQUIREMENTS</b><ul>{JSON.parse(task.requirements).map((r:string,i:number)=><li key={i}>{r}</li>)}</ul></div>}{task.final&&!(["running","waiting_approval"].includes(task.status))&&<div className="final"><b>RESULT</b><p>{task.final}</p></div>}<Verify key={'verify'+task.id} api={api} id={task.id}/>{task.checkpoint && ['blocked','paused','completed'].includes(task.status)&&<button onClick={()=>act(()=>api('/tasks/'+task.id+'/restore','POST'))}>Restore starting checkpoint</button>}<TaskReview key={task.id} task={{id:task.id,request:task.request,status:task.status,final:task.final,events:task.events,approvals:task.approvals}}/><div className="timeline">{task.events.filter((e:Item)=>e.kind!=='tool').reverse().map((e:Item)=><details key={e.id} open={['clarification','error','review'].includes(e.kind)}><summary><span className="event-dot"/> {e.kind.replace('_',' ')} <small>{e.created}</small></summary><pre>{format(e.content)}</pre></details>)}</div>{['blocked','paused'].includes(task.status)&&<div className="reply"><input value={message} onChange={e=>setMessage(e.target.value)} placeholder="Add clarification or instructions"/><button disabled={!message.trim()} onClick={()=>act(async()=>{await api(`/tasks/${task.id}/message`,'POST',{content:message});setMessage('');})}>Send & resume</button></div>}</div>:<div className="empty card"><h3>No task selected</h3><p>Start a task to see its plan, actions, and verification here.</p></div>}</section>
  <aside className="right-column"><div className="section-heading"><div><h2>Recent tasks</h2></div></div><div className="task-list">{tasks.length===0?<p className="muted">No tasks yet.</p>:tasks.map(t=><button className={'task-item '+(selected===t.id?'selected':'')} key={t.id} onClick={()=>{setSelected(t.id);setTab('Workspace')}}><span className="task-symbol">↗</span><span><strong>{t.request}</strong><small>#{t.id} · {t.status.replace('_',' ')}</small></span><span>›</span></button>)}</div></aside></div>}
  {tab==='Approvals'&&<section className="page-column"><div className="notice">Actions run only after you approve their exact contents. Commands can change files outside the selected project; review them carefully.</div>{approvals.length===0?<div className="empty card"><h3>All clear</h3><p>There are no actions waiting for your review.</p></div>:approvals.map(a=><div className="card approval" key={a.id}><div className="approval-head"><div><span className="kicker">{a.task_id?'TASK #'+a.task_id:'TOOL IMPORT'}</span><h3>{a.action.replace('_',' ')}</h3></div><span className="badge">{a.status}</span></div><ApprovalDetails approval={a}/>{a.result&&<p>{a.result}</p>}{a.status==='pending'&&a.task_status!=='paused'&&<div className="actions"><button onClick={()=>act(()=>api(`/approvals/${a.id}/decide`,'POST',{approved:false}))}>Deny</button><button className="primary" onClick={()=>act(()=>api(`/approvals/${a.id}/decide`,'POST',{approved:true}))}>Approve action</button>{a.action==='run_check'&&<button onClick={()=>act(()=>api('/approvals/'+a.id+'/decide','POST',{approved:true,remember:true}))}>Always allow this check here</button>}</div>}{a.status==='interrupted'&&<button onClick={()=>act(()=>api(`/approvals/${a.id}/acknowledge`,'POST'))}>I inspected the workspace</button>}</div>)}</section>}
  {tab==='Memory'&&<section className="page-column"><div className="notice">Memories stay local. Clear preferences you state in a task, such as “I prefer Python”, are saved automatically. You can add, change, disable, or remove memories anytime.</div><div className="card form-card"><label>New memory<textarea rows={3} value={memory} onChange={e=>setMemory(e.target.value)} placeholder="For example: Prefer clear, simple explanations."/></label><button className="primary" disabled={!memory.trim()} onClick={()=>act(async()=>{await api('/memories','POST',{content:memory});setMemory('')})}>Save memory</button></div>{memories.map(m=><div className="card memory-row" key={m.id}><div><textarea defaultValue={m.content} id={'memory'+m.id} rows={2}/><small>Source: {m.source} · Updated {m.updated}</small></div><div className="actions"><button onClick={()=>act(()=>api('/memories/'+m.id,'PUT',{content:(document.getElementById('memory'+m.id) as HTMLTextAreaElement).value,enabled:!!m.enabled}))}>Save</button><button onClick={()=>act(()=>api('/memories/'+m.id,'PUT',{content:m.content,enabled:!m.enabled}))}>{m.enabled?'Disable':'Enable'}</button><button onClick={()=>act(()=>api('/memories/'+m.id,'DELETE'))}>Delete</button></div></div>)}</section>}
  {tab==='Tools'&&<section className="page-column"><BuiltInTools/><div className="notice">Imports are untrusted and disabled by default. Review the source before enabling. No setup scripts run automatically.</div><div className="card form-card"><label>GitHub repository or file URL<input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://github.com/owner/repository"/></label><button className="primary" disabled={!url.trim()} onClick={()=>act(async()=>{await api('/skills/import','POST',{url});setUrl('');setTab('Approvals');})}>Review download →</button></div>{skills.map(s=><div className="card skill" key={s.id}><div><span className="kicker">{s.enabled?'ENABLED':'DISABLED'} · {s.version.slice(0,12)}</span><h3>{s.name}</h3><p>{s.source}</p><small>{s.path}</small></div><div className="actions"><button onClick={()=>act(async()=>setInspection({name:s.name,...await api(`/skills/${s.id}/inspect`)}))}>Inspect</button><button onClick={()=>act(()=>api(`/skills/${s.id}`,'PUT',{enabled:!s.enabled}))}>{s.enabled?'Disable':'Enable'}</button><button onClick={()=>act(async()=>{await api(`/skills/${s.id}`,'DELETE');setTab('Approvals')})}>Remove tool</button></div></div>)}{inspection&&<div className="card"><div className="approval-head"><h3>{inspection.name}</h3><button onClick={()=>setInspection(null)}>Close</button></div><p>Files: {inspection.files.join(', ')}</p><pre>{inspection.content}</pre></div>}</section>}
  {tab==='Settings'&&<section className="page-column settings-page"><ThemePicker/><div className="card form-card model-settings"><h2>Local model</h2><label>API base URL<input value={modelUrl} onChange={e=>setModelUrl(e.target.value)}/></label><label>Model name<input value={modelName} onChange={e=>setModelName(e.target.value)}/></label><div className="actions"><button className="primary" onClick={()=>act(async()=>{await api('/settings','PUT',{model_url:modelUrl,model_name:modelName});await getStatus()})}>Save connection</button><button onClick={()=>getStatus()}>Check connection</button></div><p>Runtime: {status.runtime_error?'Not connected':status.models?'Connected':'Checking…'} · Ollama {status.ollama_installed?'detected':'not detected'} · Git {status.git_installed?'detected':'not detected'}</p><p>Available models: {status.models?.length?status.models.join(', '):'None detected'}</p><p>System: {status.platform || 'Unknown'} · RAM: {status.memory_gib ? `${status.memory_gib} GiB` : 'Not detected'}</p>{status.runtime_error&&<small>{status.runtime_error}</small>}</div><Engineering api={api} models={status.models||[]}/></section>}
  </main></div>;
}
function ApprovalDetails({approval}: {approval: Item}) {
  const args = JSON.parse(approval.args);
  return <>
    {approval.project && <p className="approval-project">Project <code>{approval.project}</code></p>}
    {approval.action === 'replace_text' ? <div className="edit-preview">
      <p>File <code>{args.path}</code></p>
      <div className="edit-preview-columns">
        <div><strong>Exact text to remove</strong><pre>{args.old_text}</pre></div>
        <div><strong>Replacement text</strong><pre>{args.new_text || '(empty)'}</pre></div>
      </div>
      <p>The edit is rejected if the file changes before execution.</p>
    </div> : approval.action === 'design_page' ? <>
      <p>Create <code>{args.path}</code> · {Math.ceil(new Blob([args.content]).size / 1024)} KiB with embedded Anime.js</p>
      <details><summary>Inspect the complete HTML</summary><pre>{args.content}</pre></details>
    </> : <pre>{format(approval.args)}</pre>}
    {approval.status === 'pending' && approval.task_status === 'paused' && <p>Resume the task to decide on this action.</p>}
  </>;
}
function BuiltInTools() {
  const [catalog, setCatalog] = useState<{name:string; description:string}[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api('/project-tools')
      .then(projectTools => { if (active) setCatalog(projectTools); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);
  return <div className="card form-card built-in-tools">
    <h2>Built-in tools</h2>
    {error && <p role="alert">{error}</p>}
    <dl>{catalog.map(tool => <React.Fragment key={tool.name}>
      <dt>{tool.name}</dt><dd>{tool.description}</dd>
    </React.Fragment>)}</dl>
  </div>;
}
function format(value:string){try{return JSON.stringify(JSON.parse(value),null,2)}catch{return value}}
createRoot(document.getElementById('root')!).render(<App/>);
