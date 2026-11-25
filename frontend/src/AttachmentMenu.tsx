import { Globe2, ImagePlus, Plus } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

export type PageSession = {id: string; title: string; url: string};
export const imageTypes = ['image/png', 'image/jpeg', 'image/webp'];

type Props = {
  disabled: boolean;
  pages: PageSession[];
  onOpen: () => void;
  onImage: (file: File) => void;
  onPage: (id: string) => void;
};

export default function AttachmentMenu({disabled, pages, onOpen, onImage, onPage}: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const upload = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    upload.current?.focus();
    function outside(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  return <div className="attachment-menu" ref={root}
    onKeyDown={event => {
      if (event.key === 'Escape' && open) {
        event.stopPropagation();
        close();
      }
    }}
    onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
    <input ref={input} type="file" accept={imageTypes.join(',')} hidden aria-label="Image file"
      onChange={event => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (file) onImage(file);
      }}/>
    <button type="button" className="icon-button attachment-trigger" ref={trigger} disabled={disabled}
      aria-label="Add attachment" aria-expanded={open} aria-controls={open ? menuId : undefined}
      title="Add attachment" onClick={() => {
        if (!open) onOpen();
        setOpen(!open);
      }}>
      <Plus size={20} aria-hidden="true"/>
    </button>
    {open && <div id={menuId} className="attachment-popover" role="group" aria-label="Attachments">
      <button type="button" ref={upload} onClick={() => {
        close();
        input.current?.click();
      }}>
        <ImagePlus size={18} aria-hidden="true"/>
        <span>Upload image<small>PNG, JPG or WebP · up to 3 MB</small></span>
      </button>
      {pages.length > 0 && <div className="attachment-pages">
        <p>Browser previews</p>
        {pages.map(page => <button type="button" key={page.id} title={page.url} onClick={() => {
          close();
          onPage(page.id);
        }}>
          <Globe2 size={17} aria-hidden="true"/><span>{page.title || page.url}</span>
        </button>)}
      </div>}
    </div>}
  </div>;
}
