import { useRef, useState } from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { WorkspaceFrame } from "@/components/ui/workspace-frame";
import { SurfaceState, type SurfaceStateKind } from "@/components/ui/surface-state";
import { Sheet } from "@/components/ui/sheet";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EpistemicLabel } from "@/components/ui/epistemic-label";

const meta = {
  title: "Foundation/Workspace frame",
  component: WorkspaceFrame,
  parameters: { layout: "fullscreen" },
  args: { title: "Foundation workspace", children: null },
} satisfies Meta<typeof WorkspaceFrame>;
export default meta;
type Story = StoryObj<typeof meta>;

export function FoundationExample() {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <WorkspaceFrame
        title="Foundation workspace"
        actions={<Button className="min-h-11" onClick={() => setOpen(true)}>Open foundation dialog</Button>}
        detail={<div><h2 className="text-lg font-semibold">Record detail</h2><p className="workspace-prose">Synthetic source evidence remains available.</p><EpistemicLabel role="source" /></div>}
      >
        <p className="workspace-prose mb-4">Synthetic records demonstrate the foundation without new routes or data operations.</p>
        <ul aria-label="Working records" className="grid gap-4">
          <li className="rounded border p-3">
            <h2 className="text-lg font-semibold">Synthetic record title</h2>
            <dl className="grid gap-2"><div><dt>State</dt><dd>Needs review</dd></div><div><dt>Due</dt><dd>Tomorrow</dd></div><div><dt>Error</dt><dd>No error reported</dd></div></dl>
            <EpistemicLabel role="source" />
          </li>
        </ul>
      </WorkspaceFrame>
      <Dialog open={open} onClose={() => setOpen(false)} title="Foundation input">
        <label className="grid gap-2">Record title<Input defaultValue="Synthetic draft" /></label>
        <Button className="mt-4 min-h-11" onClick={() => setOpen(false)}>Cancel</Button>
      </Dialog>
    </div>
  );
}

export const Foundation: Story = { render: () => <FoundationExample /> };

const kinds: readonly SurfaceStateKind[] = ["loading", "empty", "partial", "unavailable", "not_found", "validation", "conflict"];
export const StateVocabulary: Story = {
  render: function StateExamples() {
    const [notice, setNotice] = useState("");
    return (
      <WorkspaceFrame title="State vocabulary">
        <h2 className="px-4 text-lg font-semibold">Read and write states</h2>
        <div className="grid gap-4 p-4">
          {kinds.map((kind) => <SurfaceState key={kind} kind={kind} title={`${kind} records`} testId={`foundation-${kind}`} onRetry={() => setNotice("Read requested; no successful outcome claimed.")} />)}
          <p role="status">{notice}</p>
        </div>
      </WorkspaceFrame>
    );
  },
};

export function RemovedInvokerExample() {
  const [open, setOpen] = useState(false);
  const [showInvoker, setShowInvoker] = useState(true);
  return (
    <WorkspaceFrame title="Changing workspace" actions={showInvoker ? <Button onClick={() => setOpen(true)}>Open removable dialog</Button> : undefined}>
      <p>Synthetic workspace remains available after the action changes.</p>
      <Dialog open={open} onClose={() => setOpen(false)} title="Changing action">
        <Button onClick={() => setShowInvoker(false)}>Remove originating action</Button>
      </Dialog>
    </WorkspaceFrame>
  );
}

export const RemovedInvoker: Story = { render: () => <RemovedInvokerExample /> };

export function SurvivingRowExample() {
  const [open, setOpen] = useState(false);
  const [showInvoker, setShowInvoker] = useState(true);
  const survivor = useRef<HTMLButtonElement>(null);
  return (
    <WorkspaceFrame title="Surviving records" actions={showInvoker ? <Button onClick={() => setOpen(true)}>Open departing record</Button> : undefined}>
      <Button ref={survivor}>Surviving record</Button>
      <Sheet open={open} onOpenChange={(next) => {
        setOpen(next);
        if (!next) requestAnimationFrame(() => survivor.current?.focus());
      }} title="Departing record">
        <Button onClick={() => setShowInvoker(false)}>Remove originating record</Button>
      </Sheet>
    </WorkspaceFrame>
  );
}

export const SurvivingRow: Story = { render: () => <SurvivingRowExample /> };
