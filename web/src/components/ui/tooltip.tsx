"use client";
import * as T from "@radix-ui/react-tooltip";
export const TooltipProvider = T.Provider; export const Tooltip = T.Root; export const TooltipTrigger = T.Trigger;
export const TooltipContent = ({ className = "", sideOffset = 6, ...props }: T.TooltipContentProps) => <T.Portal><T.Content sideOffset={sideOffset} className={`z-50 rounded bg-text-primary px-2 py-1 text-xs text-canvas shadow ${className}`} {...props} /></T.Portal>;
