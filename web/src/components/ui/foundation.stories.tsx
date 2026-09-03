import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { MoreHorizontal, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RichContent } from "@/components/ui/rich-content";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { SurfaceState } from "@/components/ui/surface-state";
import { LiveAnnouncement } from "@/components/ui/live-region";
import { TextField } from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const meta = {
  title: "Foundation/Component gallery",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

function ControlGallery() {
  const [sheetOpen, setSheetOpen] = useState(false);
  return (
    <div className="grid max-w-3xl gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button>Primary action</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="danger">Destructive</Button>
        <Button pending>Working</Button>
        <IconButton label="Search">
          <Search size={18} />
        </IconButton>
      </div>
      <label className="grid gap-1 text-sm font-medium">
        Search records
        <Input placeholder="Synthetic query" />
      </label>
      <label className="grid gap-1 text-sm font-medium">
        Notes
        <Textarea defaultValue="Synthetic evidence note" />
      </label>
      <label className="grid gap-1 text-sm font-medium">
        Status
        <Select defaultValue="review">
          <option value="review">Needs review</option>
          <option value="confirmed">Confirmed</option>
        </Select>
      </label>
      <Tabs defaultValue="source">
        <TabsList aria-label="Evidence views">
          <TabsTrigger value="source">Source</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="source" className="pt-3">
          Source evidence is available.
        </TabsContent>
        <TabsContent value="history" className="pt-3">
          No accepted changes.
        </TabsContent>
      </Tabs>
      <div className="flex flex-wrap gap-3">
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="secondary">Open popover</Button>
          </PopoverTrigger>
          <PopoverContent>Freshness and provenance details.</PopoverContent>
        </Popover>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="secondary">
              Actions <MoreHorizontal size={18} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem>Open evidence</DropdownMenuItem>
            <DropdownMenuItem>Copy reference</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <IconButton label="Search help">
                <Search size={18} />
              </IconButton>
            </TooltipTrigger>
            <TooltipContent>Search currently loaded records</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <Button variant="secondary" onClick={() => setSheetOpen(true)}>
          Open sheet
        </Button>
      </div>
      <TextField
        label="Correction"
        hint="The original proposal is preserved."
        error="A correction has to carry the value you are accepting instead."
        required
        defaultValue=""
      />
      <LiveAnnouncement tone="alert">Conflict: compare every canonical field, then reapply deliberately.</LiveAnnouncement>
      <Sheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="Inspector"
        description="Synthetic component-review content"
      >
        Source, freshness, provenance, and limitations appear here.
      </Sheet>
    </div>
  );
}

export const ControlsAndOverlays: Story = { render: () => <ControlGallery /> };

const ROLES: EpistemicRole[] = [
  "source",
  "ai-derived",
  "user-confirmed",
  "canonical",
  "proposed",
  "needs-review",
  "ambiguous",
  "conflicted",
  "stale",
  "superseded",
  "unavailable",
  "pipeline-incomplete",
];

export const EpistemicAndContent: Story = {
  render: () => (
    <div className="grid max-w-3xl gap-6">
      <div className="flex flex-wrap gap-2">
        {ROLES.map((role) => (
          <EpistemicLabel key={role} role={role} />
        ))}
      </div>
      <RichContent
        nodes={[
          { type: "heading", text: "Synthetic evidence" },
          { type: "paragraph", text: "A semantic paragraph with no raw HTML execution.", epistemic: "source" },
          { type: "paragraph", text: "A model summary remains labelled as AI derived.", epistemic: "ai-derived" },
          { type: "quote", text: "A source excerpt remains visibly distinct." },
          { type: "list", ordered: true, items: ["Source attribution", { text: "Freshness", children: ["Limitations"] }] },
          {
            type: "table",
            caption: "Coverage",
            headers: ["Field", "State"],
            rows: [["Authority", "accepted"]],
          },
          { type: "code", text: "record.status = 'proposed'" },
          { type: "link", text: "Open an allowed HTTPS reference", href: "https://example.test" },
        ]}
      />
    </div>
  ),
};

export const ShellStates: Story = {
  render: () => (
    <div className="grid max-w-3xl gap-4">
      <SurfaceState kind="empty" title="Nothing captured yet" />
      <SurfaceState
        kind="degraded"
        title="Knowledge is partial"
        detail="The backend disclosed incomplete coverage."
        limitations={["One synthetic source is unavailable"]}
      />
      <SurfaceState
        kind="unavailable"
        title="People could not be read"
        detail="Retry after the same-origin capability is available."
      />
      <SurfaceState
        kind="not_implemented"
        title="Intelligence is not available in this build"
      />
    </div>
  ),
};
