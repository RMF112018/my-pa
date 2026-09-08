import type {
  GoodNotesAuthority,
  GoodNotesInterpretation,
  GoodNotesInterpretationItem,
} from "@/lib/api/decode/capabilities/goodnotes.read";
import { CorrectionForm } from "@/components/goodnotes/correction-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { RichContent } from "@/components/ui/rich-content";

function itemKey(item: GoodNotesInterpretationItem, index: number): string {
  return item.occurrence_id ?? item.review_case_id ?? item.proposal_id ?? `item-${index}`;
}

function hasReviewCase(item: GoodNotesInterpretationItem): boolean {
  return Boolean(item.review_case_id?.trim());
}

function hasOccurrence(item: GoodNotesInterpretationItem): boolean {
  return Boolean(item.occurrence_id?.trim());
}

function hasTranscription(item: GoodNotesInterpretationItem): boolean {
  return typeof item.transcription === "string" && item.transcription.length > 0;
}

function authorityTone(authority: GoodNotesAuthority): "neutral" | "gold" | "coral" | "green" {
  switch (authority) {
    case "source":
    case "user_confirmed":
      return "green";
    case "pending_review":
    case "processing":
      return "gold";
    case "rejected":
    case "unavailable":
      return "coral";
    default:
      return "neutral";
  }
}

function InterpretationItemCard({
  item,
  index,
}: {
  item: GoodNotesInterpretationItem;
  index: number;
}) {
  const pending = hasReviewCase(item);
  const occurrenceId = item.occurrence_id?.trim() ?? "";

  return (
    <Card data-testid="goodnotes-interpretation-item">
      <CardTitle>Item {index + 1}</CardTitle>
      <CardBody>
        {hasTranscription(item) && item.transcription ? (
          <div data-testid="goodnotes-transcription">
            <RichContent nodes={[{ type: "paragraph", text: item.transcription }]} />
          </div>
        ) : (
          <p data-testid="goodnotes-no-transcription">This record carries no transcription.</p>
        )}
        {pending ? (
          <p className="mt-3" data-testid="goodnotes-pending-review">
            This item has a pending review case. Decide it on{" "}
            <a
              href="/review"
              className="inline-flex min-h-11 items-center text-moss-green underline"
            >
              Review
            </a>
            . A GoodNotes correction is not submitted while review is pending.
          </p>
        ) : hasOccurrence(item) ? (
          <CorrectionForm
            occurrenceId={occurrenceId}
            initialTranscription={hasTranscription(item) ? (item.transcription ?? "") : ""}
          />
        ) : null}
      </CardBody>
    </Card>
  );
}

export function InterpretationPanel({
  interpretation,
}: {
  interpretation: GoodNotesInterpretation;
}) {
  return (
    <div data-testid="goodnotes-interpretation" className="flex flex-col gap-3">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">authority</span>
        <Badge tone={authorityTone(interpretation.authority)}>{interpretation.authority}</Badge>
      </p>
      {interpretation.items.length === 0 ? (
        <p data-testid="goodnotes-no-items">This record carries no transcription.</p>
      ) : (
        interpretation.items.map((item, index) => (
          <InterpretationItemCard key={itemKey(item, index)} item={item} index={index} />
        ))
      )}
    </div>
  );
}
