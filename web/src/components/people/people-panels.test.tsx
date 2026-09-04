import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  ASSIGNMENT,
  ENTITY_SUMMARY,
  PROFILE,
  RESOLUTION,
  UNRESOLVED_MENTION,
} from "@/lib/api/decode/capabilities/_entity-fixtures";
import type { EntitySummary } from "@/lib/api/decode/capabilities/entities.search";
import type { EntityProfileView } from "@/lib/api/decode/capabilities/entities.profile";
import type { EntityResolutionView } from "@/lib/api/decode/capabilities/entities.resolve";
import type { AssignmentView } from "@/lib/api/decode/capabilities/entities.assignments.list";
import type { UnresolvedMentionView } from "@/lib/api/decode/capabilities/entities.unresolved_mentions";
import { peopleEntity, peopleHome } from "@/lib/routes/people";
import { SearchHits } from "./search-hits";
import { ResolvePanel } from "./resolve-panel";
import { EntityProfilePanel } from "./entity-profile";
import { AssignmentsPanel } from "./related-records";
import { UnresolvedMentionsPanel } from "./unresolved-mentions";
import { PeopleSearchForm, PeopleResolveForm } from "./people-forms";
import { SurfaceState } from "@/components/ui/surface-state";

afterEach(cleanup);

function noMerge(container: HTMLElement) {
  expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
  expect(screen.queryByRole("link", { name: /merge/i })).toBeNull();
  expect(container.textContent ?? "").not.toMatch(/\bMerge\b/);
}

describe("canonical People routes", () => {
  it("keeps search on /people and profiles on /people/{id}", () => {
    expect(peopleHome()).toBe("/people");
    expect(peopleEntity("ent_aaaaaaaa11111111")).toBe("/people/ent_aaaaaaaa11111111");
  });
});

describe("search hits", () => {
  it("links each hit to the canonical entity path", () => {
    render(<SearchHits entities={[ENTITY_SUMMARY as EntitySummary]} />);
    const link = screen.getByRole("link", { name: "Pat Synthetic" });
    expect(link).toHaveAttribute("href", peopleEntity(ENTITY_SUMMARY.entity_id));
    expect(link.getAttribute("href")).not.toMatch(/entityId=/);
  });

  it("renders nothing to merge", () => {
    const { container } = render(<SearchHits entities={[ENTITY_SUMMARY as EntitySummary]} />);
    noMerge(container);
  });
});

describe("search empty, degraded, and unavailable", () => {
  it("empty is a successful no-match", () => {
    render(
      <SurfaceState
        kind="empty"
        title="No entity of yours matched those words"
        testId="people-search-empty"
      />,
    );
    expect(screen.getByTestId("people-search-empty")).toHaveAttribute("data-state", "empty");
  });

  it("degraded incomplete search is not an empty directory", () => {
    render(
      <SurfaceState
        kind="degraded"
        title="The search was incomplete and returned nothing"
        testId="people-search-degraded-empty"
      />,
    );
    expect(screen.getByTestId("people-search-degraded-empty")).toHaveAttribute("data-state", "degraded");
    expect(screen.getByTestId("people-search-degraded-empty").textContent).not.toMatch(/holds nothing/i);
  });

  it("unavailable plane is not empty", () => {
    render(
      <SurfaceState
        kind="unavailable"
        title="Your people could not be searched"
        testId="people-search-unavailable"
      />,
    );
    expect(screen.getByTestId("people-search-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.getByTestId("people-search-unavailable").textContent).not.toMatch(/holds nothing/i);
  });
});

describe("resolve outcomes", () => {
  it("keeps ambiguity visible and lists every candidate", () => {
    const { container } = render(<ResolvePanel resolution={RESOLUTION as EntityResolutionView} />);
    expect(screen.getByTestId("people-resolve-outcome").textContent).toMatch(/ambiguous/i);
    expect(screen.getByTestId("people-resolve-candidates")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open profile" })).toBeNull();
    noMerge(container);
  });

  it("does not style conflicted identifier as an exact resolve", () => {
    const resolution = {
      ...RESOLUTION,
      outcome: "conflicted_identifier" as const,
      warnings: ["identifier_claimed_by_several_entities"] as const,
    } as EntityResolutionView;
    render(<ResolvePanel resolution={resolution} />);
    expect(screen.getByTestId("people-resolve-result")).toHaveAttribute(
      "data-outcome",
      "conflicted_identifier",
    );
    expect(screen.getByTestId("people-resolve-outcome").textContent).toMatch(/conflicted_identifier/);
    expect(screen.queryByRole("link", { name: "Open profile" })).toBeNull();
    expect(screen.getByTestId("people-resolve-result").textContent).toMatch(/not an exact resolve/i);
  });

  it("does not style historical_match as an exact resolve", () => {
    const resolution = {
      ...RESOLUTION,
      outcome: "historical_match" as const,
      entity_id: RESOLUTION.candidates[0]?.entity_id ?? null,
      warnings: ["entity_is_not_current"] as const,
    } as EntityResolutionView;
    render(<ResolvePanel resolution={resolution} />);
    expect(screen.getByTestId("people-resolve-result")).toHaveAttribute("data-outcome", "historical_match");
    expect(screen.queryByRole("link", { name: "Open profile" })).toBeNull();
    expect(screen.getByTestId("people-resolve-result").textContent).toMatch(/not styled as an exact resolve/i);
  });

  it("shows not_found without inventing a person", () => {
    const resolution: EntityResolutionView = {
      outcome: "not_found",
      entity_id: null,
      candidates: [],
      warnings: [],
      candidates_were_truncated: false,
    };
    render(<ResolvePanel resolution={resolution} />);
    expect(screen.getByTestId("people-resolve-outcome").textContent).toMatch(/not_found/);
    expect(screen.queryByTestId("people-resolve-candidates")).toBeNull();
  });

  it("links an exact resolve to the canonical profile", () => {
    const resolution: EntityResolutionView = {
      outcome: "resolved_exact",
      entity_id: ENTITY_SUMMARY.entity_id,
      candidates: [],
      warnings: [],
      candidates_were_truncated: false,
    };
    render(<ResolvePanel resolution={resolution} />);
    expect(screen.getByRole("link", { name: "Open profile" })).toHaveAttribute(
      "href",
      peopleEntity(ENTITY_SUMMARY.entity_id),
    );
  });
});

describe("merged-away entity", () => {
  it("names the survivor only when superseded_by_entity_id is supplied", () => {
    const merged = {
      ...PROFILE,
      entity: {
        ...PROFILE.entity,
        status: "merged_redirect",
        superseded_by_entity_id: "ent_bbbbbbbb22222222",
      },
    } as EntityProfileView;
    const { container } = render(<EntityProfilePanel profile={merged} />);
    expect(screen.getByTestId("people-merged-redirect")).toBeTruthy();
    expect(screen.getByTestId("people-survivor-link")).toHaveAttribute(
      "href",
      peopleEntity("ent_bbbbbbbb22222222"),
    );
    noMerge(container);
  });

  it("does not invent a survivor when the identifier is missing", () => {
    const merged = {
      ...PROFILE,
      entity: { ...PROFILE.entity, status: "merged_redirect", superseded_by_entity_id: null },
    } as EntityProfileView;
    render(<EntityProfilePanel profile={merged} />);
    expect(screen.getByTestId("people-survivor-missing")).toBeTruthy();
    expect(screen.queryByTestId("people-survivor-link")).toBeNull();
  });
});

describe("current vs historical assignments", () => {
  it("groups from is_current and status without mocked time", () => {
    const mixed = [
      { ...ASSIGNMENT, assignment_id: "asn_now000000000001", is_current: true, status: "active", role: "Current role" },
      { ...ASSIGNMENT, assignment_id: "asn_then00000000001", is_current: false, status: "ended", role: "Former role" },
    ] as AssignmentView[];
    render(
      <AssignmentsPanel assignments={mixed} disclosure={null} unavailable={null} />,
    );
    expect(screen.getByTestId("people-assignments-current").textContent).toMatch(/Current role/);
    expect(screen.getByTestId("people-assignments-historical").textContent).toMatch(/Former role/);
    expect(screen.getByTestId("people-assignments-current").textContent).not.toMatch(/Former role/);
  });
});

describe("unavailable companion plane", () => {
  it("states assignments could not be read rather than emptying the person", () => {
    render(
      <AssignmentsPanel
        assignments={null}
        disclosure={null}
        unavailable="the application gateway did not answer"
      />,
    );
    expect(screen.getByTestId("people-assignments-unavailable")).toHaveAttribute("data-state", "unavailable");
  });
});

describe("forms and unresolved mentions", () => {
  it("labels search and resolve without a merge control", () => {
    const { container } = render(
      <>
        <PeopleSearchForm query="" />
        <PeopleResolveForm reference="" />
      </>,
    );
    expect(screen.getByRole("searchbox", { name: "Search people" })).toBeTruthy();
    expect(screen.getByLabelText("Resolve a reference")).toBeTruthy();
    noMerge(container);
  });

  it("omits unresolved mentions that have no disclosed display name", () => {
    const { container } = render(
      <UnresolvedMentionsPanel
        mentions={[{ ...UNRESOLVED_MENTION, mention_display_name: null } as UnresolvedMentionView]}
        disclosure={{
          scope: "people",
          coverage: "complete",
          freshnessAt: null,
          authority: "derived",
          limitations: [],
          truncated: false,
        }}
      />,
    );
    expect(screen.queryByTestId("people-unresolved")).toBeNull();
    expect(container.textContent).not.toMatch(/observed_value/);
  });

  it("renders disclosed mention summaries without a resolve control", () => {
    const { container } = render(
      <UnresolvedMentionsPanel
        mentions={[UNRESOLVED_MENTION as UnresolvedMentionView]}
        disclosure={{
          scope: "people",
          coverage: "complete",
          freshnessAt: null,
          authority: "derived",
          limitations: [],
          truncated: false,
        }}
      />,
    );
    expect(screen.getByTestId("people-unresolved").textContent).toMatch(/Pat/);
    expect(screen.queryByRole("button", { name: /resolve/i })).toBeNull();
    noMerge(container);
  });
});
