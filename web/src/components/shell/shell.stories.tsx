import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommandPalette } from "@/components/shell/command-palette";
import { NavRail } from "@/components/shell/nav";
import { UtilityRegion } from "@/components/shell/utility-region";
import { Button } from "@/components/ui/button";

const meta = {
  title: "Foundation/Successor shell",
  parameters: { layout: "fullscreen" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

function ShellHarness({ initialCollapsed = false }: { initialCollapsed?: boolean }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [utilityOpen, setUtilityOpen] = useState(true);
  const [pinned, setPinned] = useState(false);
  const [width, setWidth] = useState(360);
  const [commandOpen, setCommandOpen] = useState(false);
  return (
    <div className="flex min-h-[680px] bg-canvas text-text-primary">
      <NavRail collapsed={collapsed} onCollapsedChange={setCollapsed} />
      <main className="min-w-0 flex-1 p-6">
        <h1 className="text-2xl font-semibold">Today</h1>
        <p className="mt-2 text-text-secondary">
          Deterministic synthetic shell state for visual and accessibility review.
        </p>
        <Button className="mt-6" onClick={() => setCommandOpen(true)}>
          Open command menu
        </Button>
      </main>
      <UtilityRegion
        open={utilityOpen}
        onOpenChange={setUtilityOpen}
        pinned={pinned}
        onPinnedChange={setPinned}
        width={width}
        onWidthChange={setWidth}
      />
      <CommandPalette
        open={commandOpen}
        onOpenChange={setCommandOpen}
        onCapture={() => setCommandOpen(false)}
      />
    </div>
  );
}

export const ExpandedNavigation: Story = { render: () => <ShellHarness /> };
export const CollapsedNavigation: Story = {
  render: () => <ShellHarness initialCollapsed />,
};
export const DarkCompact: Story = {
  globals: { theme: "dark", density: "compact" },
  render: () => <ShellHarness />,
};
export const Tablet: Story = {
  parameters: { viewport: { defaultViewport: "tablet" } },
  render: () => <ShellHarness />,
};
export const Mobile: Story = {
  parameters: { viewport: { defaultViewport: "mobile" } },
  render: () => <ShellHarness />,
};
