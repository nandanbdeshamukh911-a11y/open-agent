import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';
import './chat.css';

type PageSession = {id: string; title: string; url: string};
type Message = {id: number; role: 'user' | 'assistant'; content: string; has_image?: boolean; browser_url?: string};
type ChatSummary = {id: number; title: string; status: 'ready' | 'generating' | 'failed'; error: string};
type Conversation = ChatSummary & {messages: Message[]};
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;

export default function Chat({api, onCode}: {api: Api; onCode: (message: string) => void}) {
  const [history, setHistory] = useState<ChatSummary[]>([]);
  const [id, setId] = useState<number | null>(null);
  const [chat, setChat] = useState<Conversation | null>(null);
  const [pages, setPages] = useState<PageSession[]>([]);
  const [loadingImage,setLoadingImage]=useState(false);
  const [image,setImage] = useState('');
  const [pageId, setPageId] = useState('');
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<number | null>(null);
  const requestVersion = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const current = chat?.id === id ? chat : null;
  const pending = current?.status === 'generating';
  const awaitingHistory = id !== null && !current;
  const lastUserMessage = current?.messages.slice().reverse().find(message => message.role === 'user');
  const messageCount = current?.messages.length;

  useEffect(() => {
    let active = true;
    Promise.all([api<PageSession[]>('/browser/sessions'), api<ChatSummary[]>('/chats')])
      .then(([available, list]) => { if (active) { setPages(available); setHistory(list); } })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [api]);

  useEffect(() => {
    if (id === null) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const latest = await api<Conversation>('/chats/' + id);
        if (!active) return;
        setChat(latest);
        if (latest.status === 'generating') timer = setTimeout(load, 1200);
        else setHistory(await api<ChatSummary[]>('/chats'));
      } catch (err) {
        if (active) setError((err as Error).message);
      }
    }
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [id, api, sending]);

  useEffect(() => {
    end.current?.scrollIntoView({block: 'nearest'});
  }, [id, messageCount, pending]);

  function open(next: number | null) {
    requestVersion.current += 1;
    setId(next); setLoadingImage(false); setImage('');
    setInput('');
    setPageId('');
    setError('');
    setSending(false);
    if (next === null) setChat(null);
    composer.current?.focus();
  }

  async function send() {
    if (!input.trim() || loadingImage || sending || pending || awaitingHistory) return;
    const version = ++requestVersion.current;
    setSending(true);
    setError('');
    try {
      const path = id === null ? '/chats' : '/chats/' + id + '/messages';
      const saved = await api<{id: number}>(path, 'POST', {content: input, browser_session: pageId || null, image:image || null});
      if (version === requestVersion.current) {
        setInput('');
        setPageId('');
        setImage(''); setId(saved.id);
      }
    } catch (err) {
      if (version === requestVersion.current) setError((err as Error).message);
    } finally {
      if (version === requestVersion.current) setSending(false);
    }
  }

  async function retry() {
    setSending(true);
    setError('');
    try {
      await api('/chats/' + id + '/retry', 'POST');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  function handleKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  return <div className="chat-layout">
    <section className="card chat-panel" aria-label="Conversation">
      <div className="chat-transcript" aria-live="polite">
        {!current && !awaitingHistory && <div className="chat-empty">
          <h2>What can I help with?</h2>
          <p>Ask a question, work through an idea, or discuss a page you opened in Browser.</p>
        </div>}
        {awaitingHistory && <p className="chat-status">Loading conversation…</p>}
        {current?.messages.map(message => <article className={`chat-message ${message.role}`} key={message.id}>
          <strong>{message.role === 'user' ? 'You' : 'Open Agent'}</strong>
          <div className="chat-text">{message.content}</div>
          {message.has_image && <img className="chat-image" loading="lazy" src={`/api/chats/${id}/messages/${message.id}/image`} alt="Attached image"/>}
          {message.browser_url && <p className="chat-status">Browser context · {message.browser_url}</p>}
          {message.role === 'assistant' && <button type="button" className="text-button" onClick={async () => {
            try {
              await navigator.clipboard.writeText(message.content);
              setCopied(message.id);
            } catch {
              setError('Clipboard unavailable. Select and copy the reply directly.');
            }
          }}>{copied === message.id ? 'Copied' : 'Copy'}</button>}
        </article>)}
        {pending && <p className="chat-status" role="status">Waiting for the local model…</p>}
        {current?.status === 'failed' && <div className="chat-status" role="alert">
          <p>{current.error}</p>
          <button type="button" onClick={retry} disabled={sending}>Retry reply</button>
        </div>}
        <div ref={end} />
      </div>
      {error && <p role="alert" className="error chat-error">{error}</p>}
      <form className="chat-compose" onSubmit={submit}>
        <label htmlFor="chat-input">Message</label>
        <textarea id="chat-input" ref={composer} value={input} rows={3} maxLength={12000}
          placeholder="Message Open Agent…" onChange={event => setInput(event.target.value)} onKeyDown={handleKey} />
        {image && <div><img className="chat-image" src={image} alt="Image ready to send"/><button type="button" onClick={()=>setImage('')}>Remove image</button></div>}
        <div className="chat-actions"><label className="attachment-button">Attach image<input type="file" disabled={loadingImage||sending} accept="image/png,image/jpeg,image/webp" onChange={e=>{
          const file=e.target.files?.[0]; e.target.value='';
          if(!file) return;
          if(file.size>3000000){setError('Choose an image under 3 MB.');return;}
          const version=requestVersion.current;
          setLoadingImage(true);
          const reader=new FileReader();
          reader.onloadend=()=>{if(requestVersion.current===version)setLoadingImage(false)};
          reader.onload=()=>{if(requestVersion.current===version)setImage(String(reader.result));};
          reader.onerror=()=>setError('Could not read the image.');
          reader.readAsDataURL(file);
        }}/></label>
          {pages.length > 0 && <label className="chat-tool-label" htmlFor="chat-page">Attach browser context
            <select id="chat-page" value={pageId} onChange={event => setPageId(event.target.value)}>
              <option value="">None</option>
              {pages.map(item => <option key={item.id} value={item.id}>{item.title || item.url}</option>)}
            </select>
          </label>}
          <button className="primary" disabled={!input.trim() || loadingImage || pending || sending || awaitingHistory}>
            Send
          </button>
        </div>
      </form>
    </section>
    <aside className="card chat-history">
      <div className="chat-history-header"><h2>Conversations</h2><button type="button" onClick={() => open(null)}>New chat</button></div>
      {history.length === 0 && <p className="chat-status">Your conversations will appear here.</p>}
      {history.map(item => <button type="button" key={item.id} aria-pressed={item.id === id} className="chat-history-item"
        onClick={() => open(item.id)}>{item.title}</button>)}
      {lastUserMessage && !lastUserMessage.content.startsWith('/') && <button type="button" className="text-button"
        onClick={() => onCode(lastUserMessage.content)}>Use last message as a coding task</button>}
    </aside>
  </div>;
}
