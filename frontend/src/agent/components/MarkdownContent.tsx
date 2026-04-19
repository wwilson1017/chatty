import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

interface Props {
  content: string;
}

export default function MarkdownContent({ content }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        h1: ({ children }) => (
          <h1 className="text-xl font-bold text-ch-ink mt-4 mb-2">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-lg font-semibold text-ch-ink mt-3 mb-2">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-base font-semibold text-ch-ink mt-3 mb-1">{children}</h3>
        ),
        p: ({ children }) => (
          <p className="text-sm leading-relaxed text-ch-ink mb-3 last:mb-0">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc ml-4 text-sm text-ch-ink mb-3 space-y-1">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal ml-4 text-sm text-ch-ink mb-3 space-y-1">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="leading-relaxed">{children}</li>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            className="text-ch-gold underline hover:text-ch-gold transition-colors"
            target="_blank"
            rel="noopener noreferrer"
          >
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-ch-gold/30 pl-4 italic text-ch-ink-mute my-3">
            {children}
          </blockquote>
        ),
        code: ({ className, children, ...props }) => {
          const hasLang = className?.includes('language-') || className?.includes('hljs');
          const hasNewlines = typeof children === 'string' && children.includes('\n');
          if (hasLang || hasNewlines) {
            return <code className={className} {...props}>{children}</code>;
          }
          return (
            <code className="bg-ch-bg-raised px-1.5 py-0.5 rounded text-sm font-mono text-ch-ink" {...props}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="bg-ch-bg-elev text-green-200 rounded-md p-4 overflow-x-auto text-sm my-3 shadow-inner">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full text-sm border-collapse border border-ch-line-strong rounded-lg overflow-hidden">
              {children}
            </table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-ch-bg-raised">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left text-xs font-semibold text-ch-ink border border-ch-line-strong">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 text-sm text-ch-ink-mute border border-ch-line-strong">{children}</td>
        ),
        hr: () => <hr className="border-ch-line-strong my-4" />,
        strong: ({ children }) => <strong className="font-semibold text-ch-ink">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
