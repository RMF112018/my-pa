import type { ReactNode } from "react";

import { safeHref } from "@/lib/http/safe-href";

export { safeHref };

export type RichContentNode =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "quote"; text: string }
  | { type: "code"; text: string }
  | { type: "list"; items: readonly string[] }
  | { type: "link"; text: string; href: string };
export function RichContent({ nodes }: { nodes: readonly RichContentNode[] }) { return <div className="space-y-3 text-sm leading-6">{nodes.map((node, index): ReactNode => { if (node.type === "paragraph") return <p key={index}>{node.text}</p>; if (node.type === "heading") return <h2 key={index} className="text-lg font-semibold">{node.text}</h2>; if (node.type === "quote") return <blockquote key={index} className="border-l-4 pl-4 text-text-secondary">{node.text}</blockquote>; if (node.type === "code") return <pre key={index} className="overflow-auto rounded bg-surface-subtle p-3 font-mono text-xs"><code>{node.text}</code></pre>; if (node.type === "list") return <ul key={index} className="list-disc pl-5">{node.items.map((item) => <li key={item}>{item}</li>)}</ul>; const href = safeHref(node.href); return href ? <a key={index} className="text-interactive underline" href={href} rel={href.startsWith("http") ? "noreferrer" : undefined}>{node.text}</a> : <span key={index}>{node.text}</span>; })}</div>; }
