import {useState} from 'react';

type Event = {id:number; kind:string; content:string};
type Approval = {id:number; action:string; args:string; status:string};
type Task = {id:number; request:string; status:string; final:string; events:Event[]; approvals:Approval[]};
type Check = {requirement:string; status:string; evidence?:string; event_id?:number};

function parse(value:string) {
  try { return JSON.parse(value); } catch { return null; }
}

export default function TaskReview({task}:{task:Task}) {
  const [filter,setFilter] = useState('all');
  const review = [...task.events].reverse().find(event => event.kind === 'review');
  const checks:Check[] = review ? parse(review.content)?.checks ?? [] : [];
  const edits = task.approvals.filter(item => ['write_file','replace_text','design_page'].includes(item.action));
  const tools = task.events.filter(event => event.kind === 'tool').map(event => {
    const data = parse(event.content);
    return {id:event.id, action:String(data?.action ?? 'tool'), result:String(data?.result ?? '')};
  });
  function download() {
    const content = JSON.stringify({task:task.id, request:task.request, status:task.status, final:task.final,
      checks, edits:edits.map(edit => ({path:parse(edit.args)?.path,status:edit.status})), evidence:tools}, null, 2);
    const url = URL.createObjectURL(new Blob([content], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'open-agent-task-' + task.id + '.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="review-panel" aria-label="Task evidence">
    <div className="review-title"><h3>Task evidence</h3><button onClick={download}>Export report</button></div>
    {checks.length > 0 && <><h4>Latest model review</h4><ul>{checks.map((check,i) => <li key={i}><strong>{check.status}</strong> · {check.requirement}
      {check.event_id && <a href={'#tool-event-'+check.event_id} onClick={()=>setFilter('all')}> Evidence #{check.event_id}</a>}</li>)}</ul></>}
    {edits.length > 0 && <details><summary>File actions ({edits.length})</summary><ul>{edits.map(edit =>
      <li key={edit.id}><code>{parse(edit.args)?.path}</code> · {edit.status}</li>)}</ul></details>}
    {tools.length > 0 && <><label>Filter results <select value={filter} onChange={e=>setFilter(e.target.value)}>
      <option value="all">All tools</option>{Array.from(new Set(tools.map(t=>t.action))).map(name=><option key={name}>{name}</option>)}
    </select></label>{tools.filter(t=>filter==='all'||filter===t.action).map(t=><details id={'tool-event-'+t.id} key={t.id}>
      <summary>#{t.id} · {t.action}</summary><pre>{t.result}</pre></details>)}</>}
  </section>;
}
