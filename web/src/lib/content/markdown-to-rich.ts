/**
 * Bounded markdown → RichContent. No markdown library.
 *
 * Allowlist: ATX headings, paragraphs, unordered/ordered lists, and a
 * sole-line `[text](href)` when `safeHref` admits the href.
 *
 * Fail-closed: raw HTML, scripts, images, fences, and unknown constructs
 * are omitted. Headings are visual structure of secondary body, not
 * canonical Brief section identifiers and not item IDs.
 */
import type { RichContentNode } from "@/components/ui/rich-content";
import { safeHref } from "@/lib/http/safe-href";

const ATX = /^(#{1,6})[ \t]+(.*)$/;
const UNORDERED = /^[-*][ \t]+(.*)$/;
const ORDERED = /^\d+\.[ \t]+(.*)$/;
const SOLE_LINK = /^\[([^\]]+)\]\((.*)\)$/;
const IMAGE_LINE = /^!\[/;
const FENCE = /^```/;

function stripHtml(input: string): string {
  let text = input.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
  text = text.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "");
  text = text.replace(/<!--[\s\S]*?-->/g, "");
  text = text.replace(/<\/?[a-zA-Z][^>]*>/g, "");
  return text;
}

function headingLevel(hashes: string): 2 | 3 | 4 {
  if (hashes.length >= 4) return 4;
  if (hashes.length === 3) return 3;
  return 2;
}

function inlineText(raw: string): string {
  const withoutHtml = stripHtml(raw);
  return withoutHtml.replace(/\[([^\]]+)\]\((.*)\)/g, "$1");
}

function soleLink(text: string): { text: string; href: string } | null {
  const match = SOLE_LINK.exec(text.trim());
  if (!match) return null;
  const href = safeHref(match[2] ?? "");
  if (!href) return null;
  const label = stripHtml(match[1] ?? "").trim();
  if (label.length === 0) return null;
  return { text: label, href };
}

function flushParagraph(buffer: string[], nodes: RichContentNode[]): void {
  const joined = stripHtml(buffer.join("\n")).trim();
  buffer.length = 0;
  if (joined.length === 0) return;
  const link = soleLink(joined);
  if (link) {
    nodes.push({ type: "link", text: link.text, href: link.href });
    return;
  }
  const text = inlineText(joined).trim();
  if (text.length === 0) return;
  nodes.push({ type: "paragraph", text });
}

function flushList(
  items: string[],
  ordered: boolean,
  nodes: RichContentNode[],
): void {
  if (items.length === 0) return;
  nodes.push({ type: "list", ordered, items: [...items] });
  items.length = 0;
}

/**
 * Convert allowlisted markdown into RichContent nodes. Never throws.
 * Unknown or unsafe constructs are dropped rather than interpreted.
 */
export function markdownToRich(markdown: string): RichContentNode[] {
  const source = stripHtml(markdown.replace(/\r\n/g, "\n"));
  const lines = source.split("\n");
  const nodes: RichContentNode[] = [];
  const paragraph: string[] = [];
  const listItems: string[] = [];
  let listOrdered = false;
  let inFence = false;

  const endBlocks = (): void => {
    flushParagraph(paragraph, nodes);
    flushList(listItems, listOrdered, nodes);
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (FENCE.test(trimmed)) {
      endBlocks();
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    if (trimmed.length === 0) {
      endBlocks();
      continue;
    }
    if (IMAGE_LINE.test(trimmed)) continue;

    const heading = ATX.exec(trimmed);
    if (heading) {
      endBlocks();
      const text = inlineText(heading[2] ?? "").trim();
      if (text.length > 0) {
        nodes.push({ type: "heading", text, level: headingLevel(heading[1] ?? "#") });
      }
      continue;
    }

    const unordered = UNORDERED.exec(trimmed);
    if (unordered) {
      flushParagraph(paragraph, nodes);
      if (listItems.length > 0 && listOrdered) flushList(listItems, true, nodes);
      listOrdered = false;
      const item = inlineText(unordered[1] ?? "").trim();
      if (item.length > 0) listItems.push(item);
      continue;
    }

    const ordered = ORDERED.exec(trimmed);
    if (ordered) {
      flushParagraph(paragraph, nodes);
      if (listItems.length > 0 && !listOrdered) flushList(listItems, false, nodes);
      listOrdered = true;
      const item = inlineText(ordered[1] ?? "").trim();
      if (item.length > 0) listItems.push(item);
      continue;
    }

    flushList(listItems, listOrdered, nodes);
    paragraph.push(trimmed);
  }

  endBlocks();
  return nodes;
}
