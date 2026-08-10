import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SituationBoard } from "@/components/situation/situation-board";
import { RelationshipTimeline } from "@/components/relationship/relationship-timeline";
import {
  acceptedTimeline,
  syntheticFrames,
  syntheticPersonId,
  syntheticProjects,
  syntheticRelationshipEvents,
  syntheticSituations,
} from "@/lib/fixtures/situation";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const OTHER: PrincipalSession = { ...PRINCIPAL, principalId: "syn-bbbb0002" };


/**
 * This file's subject is the situation and timeline components, not which data provider is
 * configured. WP-06 made the synthetic fixtures refuse unless
 * `MYPA_DATA_PROVIDER=synthetic` is set explicitly, so the opt-in is stated here
 * rather than assumed — which is the point of the switch. The default-build
 * behaviour, where the fixtures refuse and the routes serve the backend or say
 * they cannot, is asserted in `src/app/api/routes.test.ts`.
 */
beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
});

afterEach(() => {
  cleanup();
});

describe("situation fixtures", () => {
  it("stamps every situation and project with the caller's own principal", () => {
    const situations = syntheticSituations(PRINCIPAL);
    const projects = syntheticProjects(PRINCIPAL);
    expect(situations.length).toBeGreaterThan(0);
    expect(projects.length).toBeGreaterThan(0);
    for (const s of situations) {
      expect(s.principalId).toBe(PRINCIPAL.principalId);
      expect(s.situationId).toContain(PRINCIPAL.principalId);
    }
    for (const p of projects) {
      expect(p.principalId).toBe(PRINCIPAL.principalId);
      expect(p.projectId).toContain(PRINCIPAL.principalId);
    }
  });

  it("gives a foreign principal a disjoint set of situations and projects (MU-AC-05)", () => {
    const mine = syntheticSituations(PRINCIPAL).map((s) => s.situationId);
    const theirs = syntheticSituations(OTHER).map((s) => s.situationId);
    expect(mine.some((id) => theirs.includes(id))).toBe(false);

    const myProjects = syntheticProjects(PRINCIPAL).map((p) => p.projectId);
    const theirProjects = syntheticProjects(OTHER).map((p) => p.projectId);
    expect(myProjects.some((id) => theirProjects.includes(id))).toBe(false);
  });

  it("binds frames to their situation and the caller's principal", () => {
    const [situation] = syntheticSituations(PRINCIPAL);
    const frames = syntheticFrames(PRINCIPAL, situation.situationId);
    expect(frames.length).toBeGreaterThan(0);
    for (const f of frames) {
      expect(f.principalId).toBe(PRINCIPAL.principalId);
      expect(f.situationId).toBe(situation.situationId);
    }
  });
});

describe("relationship timeline accepted-only gate", () => {
  it("withholds proposed (not-accepted) events from the accepted timeline", () => {
    const personId = syntheticPersonId(PRINCIPAL);
    const all = syntheticRelationshipEvents(PRINCIPAL, personId);
    const accepted = acceptedTimeline(PRINCIPAL, personId);

    // The fixture deliberately contains at least one proposed event.
    expect(all.some((e) => !e.accepted)).toBe(true);
    // The accepted timeline contains only accepted events, and fewer than all.
    expect(accepted.length).toBeLessThan(all.length);
    for (const e of accepted) {
      expect(e.accepted).toBe(true);
      expect(e.principalId).toBe(PRINCIPAL.principalId);
    }
  });

  it("returns an empty timeline for a foreign person and never leaks another partition", () => {
    // A foreign principal's person id must never resolve for this caller.
    const foreignPerson = syntheticPersonId(OTHER);
    expect(acceptedTimeline(PRINCIPAL, foreignPerson)).toHaveLength(0);
    // An unknown person id is equally empty — indistinguishable from foreign.
    expect(acceptedTimeline(PRINCIPAL, "person-unknown-999")).toHaveLength(0);
  });
});

describe("situation board", () => {
  it("renders each situation and project as a card", () => {
    render(
      <SituationBoard
        situations={syntheticSituations(PRINCIPAL)}
        projects={syntheticProjects(PRINCIPAL)}
      />,
    );
    expect(screen.getAllByTestId("situation-card")).toHaveLength(
      syntheticSituations(PRINCIPAL).length,
    );
    expect(screen.getAllByTestId("project-card")).toHaveLength(
      syntheticProjects(PRINCIPAL).length,
    );
  });

  it("shows empty states when nothing is open", () => {
    render(<SituationBoard situations={[]} projects={[]} />);
    expect(screen.getByText("No situations are open right now.")).toBeInTheDocument();
    expect(screen.getByText("No projects yet.")).toBeInTheDocument();
  });
});

describe("relationship timeline component", () => {
  it("renders only accepted events and states the accepted-only guarantee", () => {
    const personId = syntheticPersonId(PRINCIPAL);
    const accepted = acceptedTimeline(PRINCIPAL, personId);
    render(<RelationshipTimeline events={accepted} />);
    expect(screen.getByTestId("accepted-only-note")).toBeInTheDocument();
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(accepted.length);
    // Every rendered event carries the Accepted badge.
    expect(screen.getAllByText("Accepted")).toHaveLength(accepted.length);
  });

  it("shows an empty state when there are no accepted events", () => {
    render(<RelationshipTimeline events={[]} />);
    expect(screen.getByText("No accepted events on this timeline yet.")).toBeInTheDocument();
  });
});
