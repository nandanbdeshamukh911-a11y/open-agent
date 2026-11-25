import { Download, Monitor, RotateCw, Smartphone, X } from 'lucide-react';
import { MouseEvent, useEffect, useState } from 'react';
import './site-preview.css';

type Viewport = 'desktop' | 'mobile';
type Snapshot = {
  width: number;
  height: number;
  revision: number;
  title: string;
  diagnostics: string[];
};
type Props = {
  api: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
  chatId: number;
  messageId: number;
  complete: boolean;
  onClose: () => void;
};

export default function SitePreview({api, chatId, messageId, complete, onClose}: Props) {
  const [viewport, setViewport] = useState<Viewport>('desktop');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const endpoint = '/chats/' + chatId + '/preview';

  useEffect(() => {
    let active = true;
    setSnapshot(null);
    setError('');
    setBusy(true);
    api<Snapshot>(endpoint, 'POST', {message_id: messageId, viewport})
      .then(result => { if (active) setSnapshot(result); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, endpoint, messageId, viewport, reload]);

  async function interact(action: 'point' | 'scroll', args: Record<string, number>) {
    if (!snapshot || busy) return;
    setBusy(true);
    setError('');
    try {
      setSnapshot(await api<Snapshot>(endpoint + '/' + action, 'POST', {revision: snapshot.revision, ...args}));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function click(event: MouseEvent<HTMLImageElement>) {
    if (!snapshot) return;
    const box = event.currentTarget.getBoundingClientRect();
    void interact('point', {
      x: Math.floor((event.clientX - box.left) * snapshot.width / box.width),
      y: Math.floor((event.clientY - box.top) * snapshot.height / box.height),
    });
  }

  return <section className="site-preview" aria-label="Website preview">
    <header className="site-preview-top">
      <div><h2>Website preview</h2><span title={snapshot?.title || 'index.html'}>{snapshot?.title || 'index.html'}</span></div>
      <div className="site-preview-actions">
        <a className="icon-button preview-download" href={'/api' + endpoint + '/source/' + messageId}
          title="Download HTML" aria-label="Download HTML"><Download size={17}/></a>
        <button type="button" className="icon-button" title="Close preview" aria-label="Close preview"
          onClick={onClose}><X size={19}/></button>
      </div>
    </header>
    <div className="site-preview-bar">
      <div className="preview-devices" role="group" aria-label="Preview size">
        <button type="button" className="icon-button" aria-label="Desktop" title="Desktop" disabled={busy}
          aria-pressed={viewport === 'desktop'} onClick={() => setViewport('desktop')}><Monitor size={17}/></button>
        <button type="button" className="icon-button" aria-label="Phone" title="Phone" disabled={busy}
          aria-pressed={viewport === 'mobile'} onClick={() => setViewport('mobile')}><Smartphone size={17}/></button>
      </div>
      <button type="button" className="icon-button" aria-label="Reload preview" title="Reload preview" disabled={busy}
        onClick={() => setReload(value => value + 1)}><RotateCw size={16}/></button>
      {snapshot && <div className="preview-scroll">
        <button type="button" disabled={busy} onClick={() => interact('scroll', {distance: -560})}>Scroll up</button>
        <button type="button" disabled={busy} onClick={() => interact('scroll', {distance: 560})}>Scroll down</button>
      </div>}
    </div>
    {!complete && <p className="preview-note">The reply ended before the closing HTML tag. This preview uses the code that arrived.</p>}
    {error && <p className="preview-error" role="alert">{error}</p>}
    <div className="site-preview-viewport" aria-busy={busy}>
      {snapshot ? <img src={`/api/browser/sessions/chat-${chatId}/image?revision=${snapshot.revision}`}
        width={snapshot.width} height={snapshot.height} alt="Rendered website" onClick={click}
        onError={() => setError('Reload the preview to start a fresh browser session.')}/>
        : busy && <p className="muted" role="status">Rendering preview…</p>}
    </div>
    {!!snapshot?.diagnostics.length && <details className="preview-diagnostics">
      <summary>Page diagnostics ({snapshot.diagnostics.length})</summary><pre>{snapshot.diagnostics.join('\n')}</pre>
    </details>}
  </section>;
}
