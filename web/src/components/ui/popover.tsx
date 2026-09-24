"use client";
import * as P from "@radix-ui/react-popover";
export const Popover = P.Root; export const PopoverTrigger = P.Trigger;
/**
 * `container` is optional and defaults to `undefined` (Radix's own default:
 * `document.body`), so every pre-existing caller is unaffected. A caller
 * that itself renders inside a native `<dialog>`'s top layer (e.g. an
 * authoring dialog opened via `.showModal()`) can pass a node from within
 * that `<dialog>`'s own DOM subtree, so this popover's portaled content
 * stays inside the dialog's top layer instead of escaping it to
 * `document.body` — otherwise a click/Tab into the portaled content lands
 * outside the dialog, where the app shell's own root can intercept it.
 */
export const PopoverContent = ({ className = "", sideOffset = 8, container, ...props }: P.PopoverContentProps & { readonly container?: Element | DocumentFragment | null }) => <P.Portal container={container}><P.Content sideOffset={sideOffset} className={`z-50 rounded-[var(--radius-lg)] border bg-surface p-4 shadow-[var(--shadow-elevated)] ${className}`} {...props} /></P.Portal>;
