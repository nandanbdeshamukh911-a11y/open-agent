import {useEffect,useState} from 'react';

type Api = <T=any>(path:string,method?:string,body?:unknown)=>Promise<T>;
type Rule = {id:number; project:string; args:string};
type Config = {work_model:string;planning_model:string;typescript_lsp:boolean;python_lsp:boolean;mcp_servers:Record<string,string>;rules:Rule[]};

export function Engineering({api,models}:{api:Api;models:string[]}) {
  const [config,setConfig]=useState<Config|null>(null);
  const [name,setName]=useState('');
  const [url,setUrl]=useState('');
  const [feedback,setFeedback]=useState('');
  useEffect(()=>{api<Config>('/engineering').then(setConfig).catch(e=>setFeedback(e.message))},[api]);
  if(!config) return <p role="status">{feedback || 'Loading engineering settings…'}</p>;
  const update=(changes:Partial<Config>)=>{setConfig({...config,...changes});setFeedback('')};
  async function save(){
    try {await api('/engineering','PUT',config);setFeedback('Settings saved.')} catch(e){setFeedback(String(e))}
  }
  return <section className="card form-card engineering"><h2>Engineering settings</h2>
    {(['planning_model','work_model'] as const).map(key=><label key={key}>{key==='planning_model'?'Planning and review model':'Coding and exploration model'}
      <select value={config[key]} onChange={e=>update({[key]:e.target.value})}><option value="">Use default model</option>
        {Array.from(new Set([...models,config[key]].filter(Boolean))).map(model=><option key={model}>{model}</option>)}</select></label>)}
    <label className="check-option"><input type="checkbox" checked={config.python_lsp} onChange={e=>update({python_lsp:e.target.checked})}/>Run Python language diagnostics after approved Python edits</label>
    <label className="check-option"><input type="checkbox" checked={config.typescript_lsp} onChange={e=>update({typescript_lsp:e.target.checked})}/>Run TypeScript language diagnostics after approved JS and TS edits</label>
    <h3>MCP connections</h3><p>Connect a Streamable HTTP server. Each tool listing or call requires approval.</p>
    {Object.entries(config.mcp_servers).map(([server,address])=><div className="connection-row" key={server}><span>{server} · {address}</span><button onClick={()=>{const next={...config.mcp_servers};delete next[server];update({mcp_servers:next})}}>Remove</button></div>)}
    <label>Server name<input value={name} onChange={e=>setName(e.target.value)}/></label>
    <label>Endpoint URL<input type="url" value={url} onChange={e=>setUrl(e.target.value)}/></label>
    <button disabled={!name.trim()||!url.trim()} onClick={()=>{update({mcp_servers:{...config.mcp_servers,[name.trim()]:url.trim()}});setName('');setUrl('')}}>Add to settings</button>
    <button className="primary" onClick={save}>Save engineering settings</button><p role="status">{feedback}</p>
    <h3>Remembered permissions</h3>{!config.rules.length && <p>Every command currently requires approval.</p>}
    {config.rules.map(rule=><div className="connection-row" key={rule.id}><span>{rule.project} · {JSON.parse(rule.args).check}</span>
      <button onClick={async()=>{try{await api('/check-rules/'+rule.id,'DELETE');setConfig(await api('/engineering'))}catch(e){setFeedback(String(e))}}}>Revoke</button></div>)}
  </section>
}

export function Verify({api,id}:{api:Api;id:number}){
  const [recipes,setRecipes]=useState<any[]|null>(null);
  const [message,setMessage]=useState('');
  return <details><summary>Parallel verification</summary><p>Run a named check on a separate copy of this project while coding continues. A second model session reviews the result.</p>
    <button onClick={async()=>{try{setRecipes(await api('/tasks/'+id+'/checks'))}catch(e){setMessage(String(e))}}}>Discover checks</button>
    {recipes?.length===0 && <p>No named checks available at the project root.</p>}
    {recipes?.map(r=><div key={r.check}><pre>{JSON.stringify(r,null,2)}</pre><button onClick={async()=>{try{await api('/tasks/'+id+'/verify','POST',r);setMessage('Verifier started. Results appear in task activity.')}catch(e){setMessage(String(e))}}}>Run {r.check} in copy</button></div>)}
    <p role="status">{message}</p></details>
}
