import { Download, FileCode2, Maximize2, Minimize2, Monitor, RotateCw, Smartphone, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { previewDocument } from './previewDocument';
import './site-preview.css';

type Props = { chatId: number; messageId: number; complete: boolean; onClose: () => void };

export default function SitePreview({chatId, messageId, complete, onClose}: Props) {
  const [mobile, setMobile] = useState(false);
  const [full, setFull] = useState(false);
  const [revision, setRevision] = useState(0);
  const [documentHtml, setDocumentHtml] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [issues, setIssues] = useState<string[]>([]);
  const [link, setLink] = useState<URL | null>(null);
  const [notice, setNotice] = useState('');
  const panel = useRef<HTMLElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const source = `/api/chats/${chatId}/preview/source/${messageId}`;

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setTitle('');
    setIssues([]);
    setNotice('');
    setLink(null);
    setDocumentHtml('');
    async function load() {
      try {
        const response = await fetch(source, {signal: controller.signal});
        if (!response.ok) throw new Error('Could not load the saved HTML. Try reloading the preview.');
        const html = await response.text();
        if (!controller.signal.aborted) setDocumentHtml(previewDocument(html));
      } catch (err) {
        if (!controller.signal.aborted) setError((err as Error).message);
      }
    }
    void load();
    return () => controller.abort();
  }, [source, revision]);

  useEffect(() => {
    function report(event: MessageEvent) {
      const inner = frame.current?.contentWindow?.frames[0];
      const message = event.data;
      if (!inner || event.source !== inner || event.origin !== 'null' ||
          message?.source !== 'open-agent-preview' || typeof message.value !== 'string') return;
      const value = message.value.slice(0, 300);
      if (message.kind === 'title') setTitle(value);
      if (message.kind === 'notice') { setNotice(value); setLink(null); }
      if (message.kind === 'link') {
        try {
          const target = new URL(message.value);
          if (target.protocol === 'https:' || target.protocol === 'http:') {
            setLink(target); setNotice('This link leaves the preview.');
          }
        } catch { /* Ignore invalid addresses supplied by the page. */ }
      }
      if (message.kind === 'issue') setIssues(previous =>
        previous.length >= 20 || previous.includes(value) ? previous : [...previous, value]);
    }
    function resized() { setFull(document.fullscreenElement === panel.current); }
    window.addEventListener('message', report);
    document.addEventListener('fullscreenchange', resized);
    return () => {
      window.removeEventListener('message', report);
      document.removeEventListener('fullscreenchange', resized);
    };
  }, []);

  return <section className="site-preview" ref={panel} aria-label="Website preview">
    <header className="site-preview-top">
      <h2>{title || 'Website preview'}</h2>
      <div className="site-preview-actions">
        <a className="icon-button preview-download" href={source} title="Download HTML" aria-label="Download HTML"><Download size={16}/></a>
        {document.fullscreenEnabled && <button type="button" className="icon-button"
          title={full ? 'Exit full screen' : 'Full screen'} aria-label={full ? 'Exit full screen' : 'Full screen'}
          onClick={() => { (full ? document.exitFullscreen() : panel.current!.requestFullscreen())
            .catch(() => setError('Full screen is unavailable in this window.')); }}>
          {full ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}
        </button>}
        <button type="button" className="icon-button" title="Close preview" aria-label="Close preview" onClick={onClose}><X size={18}/></button>
      </div>
    </header>
    <div className="site-preview-bar">
      <button type="button" className="icon-button" aria-label="Reload preview" title="Reload preview"
        onClick={() => setRevision(value => value + 1)}><RotateCw size={16}/></button>
      <span className="preview-address"><FileCode2 size={15} aria-hidden="true"/>index.html</span>
      <div className="preview-devices" role="group" aria-label="Preview size">
        <button type="button" className="icon-button" aria-label="Desktop" title="Desktop" aria-pressed={!mobile}
          onClick={() => setMobile(false)}><Monitor size={16}/></button>
        <button type="button" className="icon-button" aria-label="Phone" title="Phone" aria-pressed={mobile}
          onClick={() => setMobile(true)}><Smartphone size={16}/></button>
      </div>
    </div>
    {!complete && <p className="preview-note">The saved HTML ends early. Some controls may be unfinished.</p>}
    {notice && <div className="preview-link-notice" role="status">
      <span>{notice} {link && <a href={link.href} target="_blank" rel="noopener noreferrer" title={link.href}>Open {link.host} in a new tab</a>}</span>
      <button className="icon-button" type="button" aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={15}/></button>
    </div>}
    {error && <p role="alert" className="preview-error">{error}</p>}
    <div className="site-preview-viewport">
      {documentHtml ? <iframe key={revision} ref={frame} className={mobile ? 'preview-phone' : undefined}
        title="Website content" sandbox="allow-scripts allow-forms" referrerPolicy="no-referrer"
        srcDoc={documentHtml}/> : !error && <p role="status">Opening preview…</p>}
    </div>
    {!!issues.length && <details className="preview-diagnostics">
      <summary>Page diagnostics ({issues.length})</summary><pre>{issues.join('\n')}</pre>
    </details>}
  </section>;
}
