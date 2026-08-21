"use client";
import * as TabsPrimitive from "@radix-ui/react-tabs";

export const Tabs = TabsPrimitive.Root;
export const TabsList = ({ className = "", ...props }: TabsPrimitive.TabsListProps) => <TabsPrimitive.List className={`inline-flex gap-1 rounded-[var(--radius-md)] bg-surface-subtle p-1 ${className}`} {...props} />;
export const TabsTrigger = ({ className = "", ...props }: TabsPrimitive.TabsTriggerProps) => <TabsPrimitive.Trigger className={`min-h-11 rounded px-3 text-sm data-[state=active]:bg-surface data-[state=active]:shadow-sm ${className}`} {...props} />;
export const TabsContent = TabsPrimitive.Content;
