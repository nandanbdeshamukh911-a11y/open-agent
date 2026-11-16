import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';
import './chat.css';

type Tool = {id: string; name: string; description: string; placeholder: string};
type Message = {id: number; role: 'user' | 'assistant'; content: string};
type ChatSummary = {id: number; title: string; status: 'ready' | 'generating' | 'failed'; error: string};
type Conversation = ChatSummary & {messages: Message[]};
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;

export default function Chat({api, onCode}: {api: Api; onCode: (message: string) => void}) {
  const [history, setHistory] = useState<ChatSummary[]>([]);
  const [id, setId] = useState<number | null>(null);
  const [chat, setChat] = useState<Conversation | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [toolId, setToolId] = useState('');
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<number | null>(null);
  const requestVersion = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const current = chat?.id === id ? chat : null;
  const tool = tools.find(item => item.id === toolId);
  const pending = current?.status === 'generating';
  const awaitingHistory = id !== null && !current;
  const lastUserMessage = current?.messages.slice().reverse().find(message => message.role === 'user');
  const messageCount = current?.messages.length;

  useEffect(() => {
    let active = true;
    Promise.all([api<Tool[]>('/chat-tools'), api<ChatSummary[]>('/chats')])
      .then(([available, list]) => { if (active) { setTools(available); setHistory(list); } })
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
    setId(next);
    setInput('');
    setToolId('');
    setError('');
    setSending(false);
    if (next === null) setChat(null);
    composer.current?.focus();
  }

  async function send() {
    if (!input.trim() || sending || pending || awaitingHistory) return;
    const version = ++requestVersion.current;
    setSending(true);
    setError('');
    try {
      const path = id === null ? '/chats' : '/chats/' + id + '/messages';
      const saved = await api<{id: number}>(path, 'POST', {content: input, tool: toolId || null});
      if (version === requestVersion.current) {
        setInput('');
        setId(saved.id);
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
          <p>Ask a question, think through an idea, or use a built-in tool.</p>
        </div>}
        {awaitingHistory && <p className="chat-status">Loading conversation…</p>}
        {current?.messages.map(message => <article className={`chat-message ${message.role}`} key={message.id}>
          <strong>{message.role === 'user' ? 'You' : 'Open Agent'}</strong>
          <div className="chat-text">{message.content}</div>
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
        <label htmlFor="chat-input">{tool?.name || 'Message'}</label>
        <textarea id="chat-input" ref={composer} value={input} rows={3} maxLength={12000}
          placeholder={tool?.placeholder || 'Message Open Agent…'} onChange={event => setInput(event.target.value)} onKeyDown={handleKey} />
        <div className="chat-actions">
          <label className="chat-tool-label" htmlFor="chat-tool">Tool
            <select id="chat-tool" value={toolId} onChange={event => setToolId(event.target.value)}>
              <option value="">None</option>
              {tools.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <button className="primary" disabled={!input.trim() || pending || sending || awaitingHistory}>
            {tool ? 'Run tool' : 'Send'}
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
