"use client";
import * as P from "@radix-ui/react-popover";
export const Popover = P.Root; export const PopoverTrigger = P.Trigger;
export const PopoverContent = ({ className = "", sideOffset = 8, ...props }: P.PopoverContentProps) => <P.Portal><P.Content sideOffset={sideOffset} className={`z-50 rounded-[var(--radius-lg)] border bg-surface p-4 shadow-[var(--shadow-elevated)] ${className}`} {...props} /></P.Portal>;
