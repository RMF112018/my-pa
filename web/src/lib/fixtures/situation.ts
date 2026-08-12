/**
 * Synthetic Situation / Project / Relationship-timeline fixtures — WP-06 (R5).
 *
 * The R5 continuity surface (Situations, Frames, Projects, and per-person
 * relationship timelines) is landed against principal-scoped synthetic data,
 * exactly as Review was in WP-05 and Pulse in WP-02. Every record is stamped
 * with the signed-in principal's id, and every disclosure is labeled
 * `coverage: "synthetic"` / `authority: "synthetic_fixture"` so the surface
 * never presents fixture data as an accepted record. Live projections from
 * the Python continuity read models replace this module when they are wired
 * through.
 *
 * Two invariants are modeled at the fixture level, mirroring the server-side
 * partition:
 *   1. A foreign principal never appears in any helper's output — the
 *      helpers key off the caller's own principal id, which is the fixture
 *      shadow of the `principal_scoped` read path (MU-AC-05).
 *   2. Only *accepted* relationship events are legible on a timeline; a
 *      proposed (not-accepted) event is withheld exactly as the Python
 *      `list_accepted_events` filters `accepted IS TRUE`.
 */
import type { PrincipalSession } from "@/contracts/identity";
import type {
  Frame,
  Project,
  RelationshipEvent,
  Situation,
} from "@/contracts/views";
import type { DisclosureEnvelope } from "@/contracts/envelope";

function disclosure(scope: string): DisclosureEnvelope {
  return {
    scope,
    coverage: "synthetic",
    freshnessAt: null,
    authority: "synthetic_fixture",
    limitations: ["Synthetic fixture data. No live sources are connected."],
    truncated: false,
  };
}

/**
 * A synthetic person id the current principal has a relationship timeline
 * for. Deterministic per principal so a foreign principal's person ids never
 * collide with the caller's own.
 */
export function syntheticPersonId(principal: PrincipalSession): string {
  return `person-${principal.principalId}-001`;
}

/** Deterministic principal-scoped Situations. */
export function syntheticSituations(principal: PrincipalSession): readonly Situation[] {
  const pid = principal.principalId;
  return [
    {
      situationId: `sit-${pid}-001`,
      principalId: pid,
      kind: "project",
      title: "North tower — foundation phase",
      description:
        "Everything that matters about the foundation phase: the pour schedule, the retaining-wall decision, and the owner's Friday update.",
      state: "active",
      referencedObjectIds: [`prj-${pid}-001`, `rev-${pid}-001`, `rev-${pid}-002`],
      updatedAt: "2026-08-05T13:20:00+00:00",
    },
    {
      situationId: `sit-${pid}-002`,
      principalId: pid,
      kind: "relationship",
      title: "Owner's rep — Dana Whitfield",
      description:
        "Continuity view for the owner's representative: recent meetings, the open commitment, and what is still uncertain.",
      state: "open",
      referencedObjectIds: [syntheticPersonId(principal)],
      updatedAt: "2026-08-05T09:05:00+00:00",
    },
  ];
}

/** Deterministic principal-scoped Frames for a situation. */
export function syntheticFrames(
  principal: PrincipalSession,
  situationId: string,
): readonly Frame[] {
  const pid = principal.principalId;
  if (situationId !== `sit-${pid}-001`) return [];
  return [
    {
      frameId: `frm-${pid}-001`,
      principalId: pid,
      situationId,
      whatMatters: [
        "The concrete pour is on tomorrow's plan.",
        "A weather hold was mentioned in yesterday's note but is unconfirmed.",
      ],
      obligations: [`rev-${pid}-001`],
      uncertainty: ["The weather hold has not been confirmed by a second source."],
      nextAuthorityPoint: "Confirm the hold with the superintendent before 3 PM.",
      disclosure: disclosure(`frame:${situationId}`),
    },
  ];
}

/** Deterministic principal-scoped Projects. */
export function syntheticProjects(principal: PrincipalSession): readonly Project[] {
  const pid = principal.principalId;
  return [
    {
      projectId: `prj-${pid}-001`,
      principalId: pid,
      name: "North tower",
      description: "Ground-up build; currently in the foundation phase.",
      state: "active",
      participants: ["Dana Whitfield (owner's rep)", "Site team"],
      openedAt: "2026-07-01T12:00:00+00:00",
      disclosure: disclosure("projects"),
    },
  ];
}

/**
 * Deterministic relationship events for a person. Includes both accepted and
 * proposed (not-accepted) events so callers can prove the accepted-only gate.
 * The helper does NOT filter — the timeline route filters — so tests can see
 * both classes here and confirm the route withholds the proposed one.
 */
export function syntheticRelationshipEvents(
  principal: PrincipalSession,
  personId: string,
): readonly RelationshipEvent[] {
  const pid = principal.principalId;
  if (personId !== syntheticPersonId(principal)) return [];
  return [
    {
      eventId: `revt-${pid}-001`,
      principalId: pid,
      personId,
      eventType: "meeting",
      occurredAt: "2026-08-04T15:00:00+00:00",
      context: "Kickoff walk-through of the foundation phase.",
      accepted: true,
      sourceRef: `srcver-${pid}-mtg-031`,
    },
    {
      eventId: `revt-${pid}-002`,
      principalId: pid,
      personId,
      eventType: "commitment",
      occurredAt: "2026-08-05T13:20:00+00:00",
      context: "You committed to send the revised concrete schedule by Friday.",
      accepted: true,
      sourceRef: `srcver-${pid}-note-014`,
    },
    {
      // Proposed, not accepted — must never appear on the timeline.
      eventId: `revt-${pid}-003`,
      principalId: pid,
      personId,
      eventType: "observation",
      occurredAt: "2026-08-05T16:00:00+00:00",
      context: "Possible concern about the retaining-wall supplier (unconfirmed).",
      accepted: false,
      sourceRef: `srcver-${pid}-note-018`,
    },
  ];
}

/** The accepted-only slice of a person's timeline — the Python parity of
 *  `list_accepted_events`. A foreign person or principal yields an empty
 *  timeline, never a disclosure that the person exists. */
export function acceptedTimeline(
  principal: PrincipalSession,
  personId: string,
): readonly RelationshipEvent[] {
  return syntheticRelationshipEvents(principal, personId).filter((e) => e.accepted);
}
