"use client";
import * as D from "@radix-ui/react-dropdown-menu";
export const DropdownMenu = D.Root; export const DropdownMenuTrigger = D.Trigger;
export const DropdownMenuContent = ({ className = "", sideOffset = 8, ...props }: D.DropdownMenuContentProps) => <D.Portal><D.Content sideOffset={sideOffset} className={`z-50 min-w-44 rounded-[var(--radius-lg)] border bg-surface p-1 shadow-[var(--shadow-elevated)] ${className}`} {...props} /></D.Portal>;
export const DropdownMenuItem = ({ className = "", ...props }: D.DropdownMenuItemProps) => <D.Item className={`flex min-h-11 cursor-default items-center rounded px-3 text-sm outline-none focus:bg-interactive-subtle ${className}`} {...props} />;
