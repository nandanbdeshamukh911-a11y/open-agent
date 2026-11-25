import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MessageBody({content}: {content: string}) {
  return <div className="chat-markdown">
    <Markdown skipHtml remarkPlugins={[remarkGfm]} components={{
      a: ({href, children}) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      img: ({alt}) => alt ? <span>{alt}</span> : null,
      table: ({children}) => <div className="markdown-table" tabIndex={0}><table>{children}</table></div>,
    }}>{content}</Markdown>
  </div>;
}
