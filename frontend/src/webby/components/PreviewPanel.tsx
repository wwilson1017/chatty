/**
 * Chatty — Webby PreviewPanel.
 * Renders a website file preview in a sandboxed iframe.
 * Adapted from CAKE OS webby-website-agent — TNC-specific URLs removed.
 */

interface PreviewData {
  file_path: string;
  preview_html: string;
  summary?: string;
  site_url?: string;
}

interface Props {
  preview: PreviewData | null;
  siteUrl?: string;
}

function injectBaseTag(html: string, baseUrl: string): string {
  const baseTag = `<base href="${baseUrl}">`;
  if (html.includes('<head>')) return html.replace('<head>', `<head>\n${baseTag}`);
  if (html.includes('<HEAD>')) return html.replace('<HEAD>', `<HEAD>\n${baseTag}`);
  if (html.match(/<html/i)) return html.replace(/(<html[^>]*>)/i, `$1\n<head>${baseTag}</head>`);
  return `<head>${baseTag}</head>\n${html}`;
}

export function PreviewPanel({ preview, siteUrl }: Props) {
  if (!preview) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8">
        <div className="text-5xl mb-4">🖥️</div>
        <p className="text-gray-400 font-medium">No preview yet</p>
        <p className="text-gray-600 text-sm mt-1 max-w-sm">
          Ask Webby to make a change and a preview will appear here so you can see what it will look like.
        </p>
      </div>
    );
  }

  const resolvedBase = preview.site_url || siteUrl || '';
  const htmlToRender = resolvedBase
    ? injectBaseTag(preview.preview_html, resolvedBase.replace(/\/?$/, '/'))
    : preview.preview_html;

  const isPHP = preview.file_path.endsWith('.php');

  return (
    <div className="flex flex-col h-full">
      {/* Banner */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
          <span className="text-sm font-mono text-gray-300">
            {preview.file_path}
          </span>
        </div>
        {preview.summary && (
          <span className="text-xs text-gray-500">{preview.summary}</span>
        )}
      </div>

      {isPHP && (
        <div className="px-4 py-2 bg-amber-950/30 border-b border-amber-800/40 text-xs text-amber-400 flex-shrink-0">
          PHP file — dynamic content (like product listings) won't render in the preview.
        </div>
      )}

      {/* Sandboxed iframe — allow-same-origin needed for <base> CSS resolution */}
      <div className="flex-1 bg-white">
        <iframe
          srcDoc={htmlToRender}
          className="w-full h-full border-0"
          sandbox="allow-same-origin"
          title={`Preview of ${preview.file_path}`}
        />
      </div>
    </div>
  );
}
