import type { ReactNode } from "react";

import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { safeHref } from "@/lib/http/safe-href";

/** Nested list item: a string, or a node that itself contains nested items. */
export type RichContentListItem =
  | string
  | { readonly text: string; readonly children?: readonly RichContentListItem[] };

/**
 * Allowlisted rich-content vocabulary. Unknown `type` values are ignored
 * (fail-closed). Text is always rendered as text, never as markup.
 */
export type RichContentNode =
  | { readonly type: "paragraph"; readonly text: string; readonly epistemic?: EpistemicRole }
  | { readonly type: "heading"; readonly text: string; readonly level?: 2 | 3 | 4 }
  | { readonly type: "quote"; readonly text: string }
  | { readonly type: "code"; readonly text: string }
  | { readonly type: "emphasis"; readonly text: string }
  | { readonly type: "strong"; readonly text: string }
  | {
      readonly type: "list";
      readonly ordered?: boolean;
      readonly items: readonly RichContentListItem[];
    }
  | {
      readonly type: "table";
      readonly caption?: string;
      readonly headers: readonly string[];
      readonly rows: readonly (readonly string[])[];
    }
  | { readonly type: "figure"; readonly caption: string; readonly alt: string; readonly src: string }
  | { readonly type: "link"; readonly text: string; readonly href: string; readonly epistemic?: EpistemicRole };

export { safeHref };

function listItems(items: readonly RichContentListItem[], ordered: boolean): ReactNode {
  return items.map((item, index) => {
    if (typeof item === "string") {
      return <li key={index}>{item}</li>;
    }
    return (
      <li key={index}>
        {item.text}
        {item.children && item.children.length > 0 ? (
          ordered ? (
            <ol className="list-decimal pl-5">{listItems(item.children, true)}</ol>
          ) : (
            <ul className="list-disc pl-5">{listItems(item.children, false)}</ul>
          )
        ) : null}
      </li>
    );
  });
}

function withEpistemic(
  key: number,
  role: EpistemicRole | undefined,
  children: ReactNode,
): ReactNode {
  if (!role) return <div key={key}>{children}</div>;
  return (
    <div key={key} className="space-y-1" data-epistemic-content={role}>
      <EpistemicLabel role={role} />
      {children}
    </div>
  );
}

export function RichContent({ nodes }: { nodes: readonly RichContentNode[] }) {
  return (
    <div className="space-y-3 text-sm leading-6">
      {nodes.map((node, index): ReactNode => {
        switch (node.type) {
          case "paragraph":
            return withEpistemic(index, node.epistemic, <p>{node.text}</p>);
          case "heading": {
            const Heading = node.level === 3 ? "h3" : node.level === 4 ? "h4" : "h2";
            return (
              <Heading key={index} className="text-lg font-semibold">
                {node.text}
              </Heading>
            );
          }
          case "quote":
            return (
              <blockquote key={index} className="border-l-4 pl-4 text-text-secondary">
                {node.text}
              </blockquote>
            );
          case "code":
            return (
              <pre
                key={index}
                className="overflow-auto rounded bg-surface-subtle p-3 font-mono text-xs"
              >
                <code>{node.text}</code>
              </pre>
            );
          case "emphasis":
            return (
              <p key={index}>
                <em>{node.text}</em>
              </p>
            );
          case "strong":
            return (
              <p key={index}>
                <strong>{node.text}</strong>
              </p>
            );
          case "list":
            return node.ordered ? (
              <ol key={index} className="list-decimal pl-5">
                {listItems(node.items, true)}
              </ol>
            ) : (
              <ul key={index} className="list-disc pl-5">
                {listItems(node.items, false)}
              </ul>
            );
          case "table":
            return (
              <table key={index} className="w-full border-collapse text-left">
                {node.caption ? <caption className="mb-2 text-left">{node.caption}</caption> : null}
                <thead>
                  <tr>
                    {node.headers.map((header) => (
                      <th key={header} className="border-b px-2 py-1 font-semibold">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {node.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="border-b px-2 py-1">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            );
          case "figure": {
            const src = safeHref(node.src);
            return (
              <figure key={index} className="space-y-1">
                {src ? (
                  // Allowlisted https/root-relative evidence crops; Next Image is out of this primitive's scope.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={src} alt={node.alt} className="max-w-full rounded border" />
                ) : (
                  <p>{node.alt}</p>
                )}
                <figcaption className="text-xs text-text-secondary">{node.caption}</figcaption>
              </figure>
            );
          }
          case "link": {
            const href = safeHref(node.href);
            const link = href ? (
              <a
                className="text-interactive underline"
                href={href}
                rel={href.startsWith("https:") ? "noreferrer" : undefined}
              >
                {node.text}
              </a>
            ) : (
              <span>{node.text}</span>
            );
            return withEpistemic(index, node.epistemic, link);
          }
          default:
            return null;
        }
      })}
    </div>
  );
}
