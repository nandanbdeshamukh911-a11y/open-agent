// The outer frame owns the navigation policy. A policy inside the generated
// page alone cannot restrict that page from navigating itself to a new origin.
const policy = [
  "default-src 'none'", "frame-src data:", "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'", "img-src data: blob:", "media-src data: blob:",
  "font-src data:", "form-action 'none'", "base-uri 'none'", "webrtc 'block'",
].join('; ');

const reporter = String.raw`<script>
  (() => {
    const report = (kind, value) => parent.parent.postMessage(
      {source: 'open-agent-preview', kind, value: String(value)}, '*');
    addEventListener('DOMContentLoaded', () => report('title', document.title));
    addEventListener('error', e => { if (e.message) report('issue', e.message); });
    addEventListener('securitypolicyviolation', e => report('issue', 'Blocked by preview policy: ' + e.effectiveDirective));
    window.addEventListener('click', e => {
      const link = e.target.closest?.('a[href]');
      const href = link?.getAttribute('href')?.trim();
      if (!href || href.startsWith('#') || e.defaultPrevented) return;
      const fragment = href.match(/^(?:\.\/)?index\.html(#.*)$/i);
      e.preventDefault();
      if (fragment) location.hash = fragment[1];
      else if (/^https?:\/\//i.test(href)) report('link', href);
      else report('notice', 'This file is missing from the single-page preview.');
    });
  })();
</script>`;

export function previewDocument(source: string): string {
  // Install error reporting before page scripts while preserving standards mode.
  const opening = source.match(/^\s*<!doctype\s+html[^>]*>/i)?.[0] ?? '';
  const html = opening + reporter + source.slice(opening.length);
  const bytes = new TextEncoder().encode(html);
  const chunks: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
  }
  const encoded = btoa(chunks.join(''));
  return `<!doctype html><html><head>
    <meta http-equiv="Content-Security-Policy" content="${policy}">
    <meta name="referrer" content="no-referrer">
    <style>html,body,iframe{width:100%;height:100%;margin:0;border:0;display:block}body{overflow:hidden;background:white}</style>
    </head><body><iframe title="Generated page" sandbox="allow-scripts allow-forms"
    referrerpolicy="no-referrer" src="data:text/html;charset=utf-8;base64,${encoded}"></iframe></body></html>`;
}
