import { FormEvent, MouseEvent, useEffect, useState } from 'react';
import './browser.css';

type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
type Session = {id: string; title: string; url: string};
type Preview = {
  title: string; url: string; status: number | null; revision: number;
  outline: string; diagnostics: string[]; width: number; height: number; overflow: number;
};

export default function Browser({api, onCode}: {api: Api; onCode: (message: string) => void}) {
  const [url, setUrl] = useState('');
  const [viewport, setViewport] = useState('desktop');
  const [id, setId] = useState('manual');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('');
  const [value, setValue] = useState('');
  const [controlName, setControlName] = useState('');
  const [controlRole, setControlRole] = useState('button');

  useEffect(() => {
    let active = true;
    api<Session[]>('/browser/sessions').then(list => {
      if (active) setSessions(list);
      if (active && list.some(session => session.id === id)) {
        return api<Preview>('/browser/sessions/' + id).then(state => {
          if (active) setPreview(state);
        });
      }
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [api, id]);

  async function perform(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await work();
      setSessions(await api<Session[]>('/browser/sessions'));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function open(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    void perform(async () => {
      const opened = await api<Preview>('/browser/open', 'POST', {url: url.trim(), viewport});
      setId('manual');
      setPreview(opened);
    });
  }

  function click(event: MouseEvent<HTMLImageElement>) {
    if (!preview || id !== 'manual') return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.floor((event.clientX - bounds.left) * preview.width / bounds.width);
    const y = Math.floor((event.clientY - bounds.top) * preview.height / bounds.height);
    void perform(async () => setPreview(await api<Preview>('/browser/point', 'POST', {x, y, revision: preview.revision})));
  }

  function fill(event: FormEvent) {
    event.preventDefault();
    if (!preview || id !== 'manual') return;
    void perform(async () => {
      setPreview(await api<Preview>('/browser/fill', 'POST', {label, value, revision: preview.revision}));
      setValue('');
    });
  }

  function activate(event: FormEvent) {
    event.preventDefault();
    if (!preview || id !== 'manual') return;
    void perform(async () => setPreview(await api<Preview>('/browser/click', 'POST', {
      role:controlRole, name:controlName, revision:preview.revision,
    })));
  }

  return <section className="browser-panel" aria-label="Integrated browser">
    <form className="browser-bar card" onSubmit={open}>
      <label htmlFor="browser-url">Address</label>
      <input id="browser-url" value={url} onChange={event => setUrl(event.target.value)}
        placeholder="http://127.0.0.1:3000 or https://example.com" maxLength={2048} />
      <select aria-label="Preview viewport" value={viewport} onChange={event => setViewport(event.target.value)}>
        <option value="desktop">Desktop</option><option value="mobile">Phone</option>
      </select>
      <button disabled={!url.trim() || busy} className="primary">Open</button>
    </form>
    <div className="browser-controls">
      <label htmlFor="browser-session">Session</label>
      <select id="browser-session" value={id} disabled={busy} onChange={event => {
        setId(event.target.value); setPreview(null); setError('');
      }}>
        <option value="manual">My preview</option>
        {sessions.filter(session => session.id !== 'manual').map(session =>
          <option key={session.id} value={session.id}>{session.id.replace('task-', 'Task #')} · {session.title || session.url}</option>
        )}
      </select>
      <button disabled={!preview || busy} onClick={() => perform(async () => setPreview(
        await api<Preview>('/browser/sessions/' + id + '/inspect', 'POST'),
      ))}>Refresh preview</button>
      <button disabled={!preview || busy} onClick={() => perform(async () => {
        await api('/browser/sessions/' + id, 'DELETE');
        setPreview(null);
        setId('manual');
      })}>Close session</button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {!preview && <div className="card empty">
      <h2>{busy ? 'Opening browser…' : 'Preview a site'}</h2>
      <p>Open a local development server or a public HTTPS page. The preview loads same-origin resources with GET and HEAD requests.</p>
    </div>}
    {preview && <div className="browser-content">
      <section className="card browser-view">
        <div className="browser-location">
          <strong>{preview.title || 'Browser preview'}</strong>
          <span>{preview.status !== null && `HTTP ${preview.status} · `}{preview.url}</span>
          <span>{preview.width} × {preview.height} · Horizontal overflow {preview.overflow}px</span>
        </div>
        <img className={id === 'manual' && !busy ? 'interactive' : ''} alt="Rendered site preview"
          width={preview.width} height={preview.height}
          src={`/api/browser/sessions/${id}/image?revision=${preview.revision}`} onClick={click} />
        <div className="browser-footer">
          {id === 'manual' && [-560, 560].map(distance => <button type="button" key={distance} disabled={busy}
            onClick={() => perform(async () => setPreview(await api<Preview>('/browser/scroll', 'POST', {distance, revision:preview.revision})))}>
            {distance < 0 ? 'Scroll up' : 'Scroll down'}
          </button>)}
          <button type="button" onClick={() => onCode(`Verify the behavior at ${preview.url} using the integrated browser. `)}>
            Use page in coding task
          </button>
          {id === 'manual' && <span>Click the preview to interact.</span>}
        </div>
      </section>
      <aside className="card browser-inspector">
        <h2>Page inspection</h2>
        <details open><summary>Accessible controls</summary><pre>{preview.outline || 'No accessible content.'}</pre></details>
        <details open><summary>Page errors and requests ({preview.diagnostics.length})</summary>
          <pre>{preview.diagnostics.join('\n') || 'No errors recorded.'}</pre>
        </details>
        {id === 'manual' && <form onSubmit={activate}>
          <label>Control role<select value={controlRole} onChange={event => setControlRole(event.target.value)}>
            {['button','link','tab','checkbox','radio','switch','menuitem','option'].map(role => <option key={role}>{role}</option>)}
          </select></label>
          <label>Exact control name<input value={controlName} onChange={event => setControlName(event.target.value)} maxLength={250} /></label>
          <button disabled={busy || !controlName.trim()}>Activate control</button>
        </form>}
        {id === 'manual' && <form onSubmit={fill}>
          <label>Exact field label<input value={label} onChange={event => setLabel(event.target.value)} maxLength={250} /></label>
          <label>Test input<input value={value} onChange={event => setValue(event.target.value)} maxLength={2000} /></label>
          <button disabled={busy || !label.trim()}>Fill field</button>
        </form>}
      </aside>
    </div>}
  </section>;
}
