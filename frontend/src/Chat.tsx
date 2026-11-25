import { ArrowUp, Check, Copy, Globe2, MessageSquare, Monitor, SquareTerminal, X } from 'lucide-react';
import { FormEvent, KeyboardEvent, lazy, Suspense, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import AttachmentMenu, { imageTypes, PageSession } from './AttachmentMenu';
import SitePreview from './SitePreview';
import './chat.css';

const MessageBody = lazy(() => import('./MessageBody'));

type Message = {
  id: number; role: 'user' | 'assistant'; content: string;
  has_image?: boolean | 0 | 1; browser_url?: string; html_preview?: {complete: boolean};
};
type ChatSummary = {id: number; title: string; status: 'ready' | 'generating' | 'failed'; error: string};
type Conversation = ChatSummary & {messages: Message[]};
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;

type Props = {
  api: Api;
  onCode: (message: string) => void;
  onFocusChat: () => void;
  historyTarget: HTMLElement | null;
  visible: boolean;
};

function LoadingDots() {
  return <div className="loading-dots" role="status" aria-label="Generating reply">
    <span aria-hidden="true"/><span aria-hidden="true"/><span aria-hidden="true"/>
  </div>;
}

export default function Chat({api, onCode, onFocusChat, historyTarget, visible}: Props) {
  const [history, setHistory] = useState<ChatSummary[]>([]);
  const [id, setId] = useState<number | null>(null);
  const [chat, setChat] = useState<Conversation | null>(null);
  const [pages, setPages] = useState<PageSession[]>([]);
  const [loadingImage, setLoadingImage] = useState(false);
  const [image, setImage] = useState<{data: string; name: string} | null>(null);
  const [pageId, setPageId] = useState('');
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<number | null>(null);
  const [previewChoice, setPreviewChoice] = useState<{latest: number; chosen: number | null} | null>(null);
  const requestVersion = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const current = chat?.id === id ? chat : null;
  const pending = current?.status === 'generating';
  const awaitingHistory = id !== null && !current;
  const lastUserMessage = current?.messages.slice().reverse().find(message => message.role === 'user');
  const latestPage = current?.messages.slice().reverse().find(message => message.html_preview);
  const selectedPreviewId = latestPage && (previewChoice?.latest === latestPage.id ? previewChoice.chosen : latestPage.id);
  const preview = current?.messages.find(message => message.id === selectedPreviewId)?.html_preview;
  const selectedPage = pages.find(page => page.id === pageId);
  const messageCount = current?.messages.length;
  const busy = loadingImage || sending || pending || awaitingHistory;

  useEffect(() => {
    let active = true;
    api<ChatSummary[]>('/chats')
      .then(list => { if (active) setHistory(list); })
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
        if (latest.status === 'generating') {
          timer = setTimeout(load, 1200);
        } else {
          const list = await api<ChatSummary[]>('/chats');
          if (active) setHistory(list);
        }
      } catch (err) {
        if (active) setError((err as Error).message);
      }
    }
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [id, api, sending]);

  useEffect(() => {
    followLatest.current = true;
  }, [id]);

  useEffect(() => {
    const viewport = transcript.current;
    const thread = viewport?.firstElementChild;
    if (!visible || !viewport || !thread) return;
    function follow() {
      if (viewport && followLatest.current) viewport.scrollTop = viewport.scrollHeight;
    }
    follow();
    // Formatted replies and images can expand after the message arrives.
    const observer = new ResizeObserver(follow);
    observer.observe(thread);
    return () => observer.disconnect();
  }, [id, messageCount, pending, visible]);

  function open(next: number) {
    onFocusChat();
    if (next === id) return;
    requestVersion.current += 1;
    setId(next);
    setPreviewChoice(null);
    setLoadingImage(false);
    setImage(null);
    setInput('');
    setPageId('');
    setError('');
    setSending(false);
  }

  function attachImage(file: File) {
    if (busy) return;
    if (!imageTypes.includes(file.type) || file.size > 3_000_000) {
      setError('Choose a PNG, JPEG or WebP image up to 3 MB.');
      return;
    }
    setError('');
    setLoadingImage(true);
    const version = requestVersion.current;
    const reader = new FileReader();
    reader.onload = () => {
      if (requestVersion.current === version) {
        setImage({data: String(reader.result), name: file.name});
        composer.current?.focus();
      }
    };
    reader.onerror = () => {
      if (requestVersion.current === version) setError('Could not read the image.');
    };
    reader.onloadend = () => {
      if (requestVersion.current === version) setLoadingImage(false);
    };
    reader.readAsDataURL(file);
  }

  async function send() {
    if (!input.trim() || busy) return;
    const version = ++requestVersion.current;
    setSending(true);
    setError('');
    try {
      const path = id === null ? '/chats' : '/chats/' + id + '/messages';
      const saved = await api<{id: number}>(path, 'POST', {
        content: input, browser_session: pageId || null, image: image?.data || null,
      });
      if (version === requestVersion.current) {
        followLatest.current = true;
        setInput('');
        setPageId('');
        setImage(null);
        setId(saved.id);
        const list = await api<ChatSummary[]>('/chats').catch(() => null);
        if (list && version === requestVersion.current) setHistory(list);
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

  return <>
    {historyTarget && createPortal(
      history.length ? history.map(item => <button type="button" key={item.id}
        className="conversation-item" aria-current={visible && item.id === id ? 'page' : undefined}
        onClick={() => open(item.id)} title={item.title}>
        <MessageSquare size={15} aria-hidden="true"/><span>{item.title}</span>
      </button>) : <p className="conversation-empty">No saved chats</p>, historyTarget,
    )}
    <div className={preview ? 'chat-surface chat-with-preview' : 'chat-surface'} hidden={!visible}>
    <div className={id === null ? 'chat-panel chat-start' : 'chat-panel'}>
      {id === null ? <section className="chat-intro">
        <h2>What are you working on?</h2>
        <p>Ask a question, share an image, or talk through a change before opening a coding task.</p>
      </section> : <div className="chat-transcript" ref={transcript} aria-label="Conversation"
        onScroll={event => {
          const viewport = event.currentTarget;
          followLatest.current = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop < 48;
        }}>
        <div className="chat-thread">
          {awaitingHistory && <p className="chat-status" role="status">Loading conversation…</p>}
          {current?.messages.map(message => <article className={`chat-message ${message.role}`} key={message.id}>
            <strong>{message.role === 'user' ? 'You' : 'Open Agent'}</strong>
            {Boolean(message.has_image) && <img className="chat-image" loading="lazy" src={`/api/chats/${id}/messages/${message.id}/image`} alt="Attached image"/>}
            {message.role === 'assistant' ? <Suspense fallback={null}>
              <MessageBody content={message.content}/>
            </Suspense> : <div className="chat-text">{message.content}</div>}
            {message.browser_url && <p className="chat-status"><Globe2 size={13} aria-hidden="true"/> {message.browser_url}</p>}
            {message.html_preview && latestPage && <button type="button" className="text-button"
              aria-pressed={selectedPreviewId === message.id}
              onClick={() => setPreviewChoice({latest: latestPage.id, chosen: message.id})}>
              <Monitor size={15} aria-hidden="true"/> Preview website
            </button>}
            {message.role === 'assistant' && <button type="button" className="icon-button copy-reply"
              aria-label={copied === message.id ? 'Copied' : 'Copy reply'} title={copied === message.id ? 'Copied' : 'Copy reply'}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(message.content);
                  setCopied(message.id);
                } catch {
                  setError('Clipboard unavailable. Select and copy the reply directly.');
                }
              }}>
              {copied === message.id ? <Check size={16}/> : <Copy size={16}/>}
            </button>}
          </article>)}
          {pending && <LoadingDots/>}
          {current?.status === 'failed' && <div className="chat-status" role="alert">
            <p>{current.error}</p>
            <button type="button" onClick={retry} disabled={sending}>Retry reply</button>
          </div>}
        </div>
      </div>}
      <div className="chat-compose-region">
        {error && <p role="alert" className="error chat-error">{error}</p>}
        <form className="chat-compose" aria-label="Compose message" onSubmit={submit}>
          {(image || pageId) && <div className="composer-attachments">
            {image && <div className="attachment-chip">
              <img src={image.data} alt="Image ready to send"/><span title={image.name}>{image.name}</span>
              <button type="button" className="icon-button" onClick={() => setImage(null)} aria-label="Remove image" title="Remove image"><X size={16}/></button>
            </div>}
            {pageId && <div className="attachment-chip">
              <Globe2 size={16} aria-hidden="true"/><span>{selectedPage?.title || selectedPage?.url || 'Browser preview'}</span>
              <button type="button" className="icon-button" onClick={() => setPageId('')} aria-label="Remove browser preview"><X size={16}/></button>
            </div>}
          </div>}
          <textarea aria-label="Message" ref={composer} value={input} rows={2} maxLength={12000}
            placeholder="Write a message…" onChange={event => setInput(event.target.value)} onKeyDown={handleKey}
            onPaste={event => {
              const file = Array.from(event.clipboardData.files).find(item => imageTypes.includes(item.type));
              if (file && !busy) {
                event.preventDefault();
                attachImage(file);
              }
            }}/>
          <div className="chat-actions">
            <AttachmentMenu pages={pages} disabled={!!busy} onImage={attachImage} onPage={setPageId}
              onOpen={() => {void api<PageSession[]>('/browser/sessions').then(setPages).catch(() => setPages([]));}}/>
            {loadingImage && <span role="status" className="chat-status">Reading image…</span>}
            {sending && !pending && <LoadingDots/>}
            <button type="submit" className="icon-button send-button" aria-label="Send message" title="Send message"
              disabled={!input.trim() || !!busy}><ArrowUp size={21} aria-hidden="true"/></button>
          </div>
        </form>
        {lastUserMessage && !lastUserMessage.content.startsWith('/') && <button type="button" className="chat-handoff"
          onClick={() => onCode(lastUserMessage.content)}>
          <SquareTerminal size={16} aria-hidden="true"/> Use last message in a coding task
        </button>}
      </div>
    </div>
    {visible && id !== null && latestPage && selectedPreviewId && preview &&
      <SitePreview key={selectedPreviewId} api={api} chatId={id} messageId={selectedPreviewId}
        complete={preview.complete} onClose={() => setPreviewChoice({latest: latestPage.id, chosen: null})}/>}
    </div>
  </>;
}
