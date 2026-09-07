/**
 * The synthetic Constraint Management corpus, and the read plane that serves it.
 *
 * **This module is the backend for this work package, and says so.** There is no
 * BFF route, no gateway capability and no Constraint read behind the workspace
 * at this head; what stands in for one is here, behind the same
 * `requireSyntheticProvider()` gate every other fixture module in this tree
 * passes through. That placement is the whole guarantee: the route imports this
 * directly, so a build that has not set `MYPA_DATA_PROVIDER=synthetic` cannot
 * obtain a single row, and the workspace states that it has no source rather
 * than rendering a Project's position out of invented numbers.
 *
 * **Every backend-derived value here is authored, never derived.** The three
 * booleans a Register row carries — `isOverdue`, `isDueSoon`, `inMyCourt` — are
 * written down per record as literal backend authority, exactly as the Project's
 * own calendar would have decided them, and are never computed from `dueDate`.
 * One record proves the separation on purpose: `cst_syn_0043` carries a due date
 * years in the past and `isOverdue: false`. A browser that recomputed urgency
 * would contradict the fixture, and the Register test asserts the fixture wins
 * (`CM-FE-AC-034`, and `04_REGISTER_PRODUCT_SPECIFICATION` §6, which asks for
 * exactly this record).
 *
 * The same rule governs the Overview: its counts are stored, not tallied from
 * `CONSTRAINT_ENTRIES`. They are deliberately *not* reconcilable by addition
 * from a single Register page, because a page is bounded and a Project's
 * position is not (`CM-FE-AC-010`).
 *
 * **What is not here is as deliberate as what is.** No record carries a raw
 * principal identifier: a `PRINCIPAL` party's filter identity is the closed
 * token `"principal"`. No `UNRESOLVED` party carries a filterable reference,
 * because the landed read plane gives it none, and a fixture that invented one
 * would make an option the real backend can never honour. No sync state outside
 * the four a persisted-row read can establish appears anywhere.
 */
import { requireSyntheticProvider } from "@/lib/fixtures/gate";
import type {
  ConstraintCategory,
  ConstraintCategoryOpenCount,
  ConstraintCategoryRef,
  ConstraintEvidenceLink,
  ConstraintHistoryEntry,
  ConstraintLifecycle,
  ConstraintListEntry,
  ConstraintOverview,
  ConstraintPartyRef,
  ConstraintRelationship,
  ConstraintSyncState,
  ConstraintView,
} from "@/contracts/constraints";

/** The one synthetic Project this corpus describes. */
export const SYNTHETIC_CONSTRAINT_PROJECT_ID = "prj_syn_0001";

/** A second Project, present so cross-Project leakage is a testable claim. */
export const SYNTHETIC_SECOND_PROJECT_ID = "prj_syn_0002";

export interface ConstraintFixtureProject {
  readonly projectId: string;
  readonly name: string;
  readonly reference: string;
}

export const SYNTHETIC_CONSTRAINT_PROJECTS: readonly ConstraintFixtureProject[] = [
  {
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    name: "Synthetic Riverside Works",
    reference: "SYN-RW-2026",
  },
  {
    projectId: SYNTHETIC_SECOND_PROJECT_ID,
    name: "Synthetic Northgate Depot",
    reference: "SYN-ND-2026",
  },
] as const;

// --- Parties -----------------------------------------------------------------
//
// Three kinds, three identity rules. A PRINCIPAL party shares one closed token
// because the acting Principal is not an entity in the partition and has no id
// this tier may carry. An ENTITY party has its persisted `ent_` identifier. An
// UNRESOLVED party has none at all, and is filterable only as the whole bucket.

const PARTY_PRINCIPAL: ConstraintPartyRef = {
  kind: "PRINCIPAL",
  partyRefId: "principal",
  displayLabel: "You",
};

function entityParty(entityId: string, displayLabel: string): ConstraintPartyRef {
  return { kind: "ENTITY", partyRefId: entityId, displayLabel, entityId };
}

function unresolvedParty(displayLabel: string): ConstraintPartyRef {
  return { kind: "UNRESOLVED", partyRefId: null, displayLabel };
}

const PARTY_DESIGN_LEAD = entityParty("ent_aaaaaaaa11111111", "Synthetic Design Lead");
const PARTY_CLIENT_PM = entityParty("ent_bbbbbbbb22222222", "Synthetic Client PM");
const PARTY_GROUNDWORKS = entityParty("ent_cccccccc33333333", "Synthetic Groundworks Ltd");
const PARTY_UTILITY = entityParty("ent_dddddddd44444444", "Synthetic Utility Provider");
const PARTY_AUTHORITY = entityParty("ent_eeeeeeee55555555", "Synthetic Highways Authority");

/** Preserved source wording from the legacy workbook. Not an identity. */
const PARTY_UNRESOLVED_STRUCTURAL = unresolvedParty("structural eng. (per log)");
const PARTY_UNRESOLVED_TBC = unresolvedParty("TBC — see log column K");

/**
 * The party options a filter may offer.
 *
 * Every option here has a stable server reference. The UNRESOLVED parties above
 * are absent by construction: they have no reference, so offering them would be
 * offering a filter the backend cannot evaluate (`CM-FE-AC-009`). What the
 * Register offers instead is the single "Unresolved" bucket, which the read
 * plane below evaluates by kind and never by label.
 */
export const SYNTHETIC_PARTY_OPTIONS: readonly ConstraintPartyRef[] = [
  PARTY_PRINCIPAL,
  PARTY_DESIGN_LEAD,
  PARTY_CLIENT_PM,
  PARTY_GROUNDWORKS,
  PARTY_UTILITY,
  PARTY_AUTHORITY,
] as const;

// --- Categories --------------------------------------------------------------

const CATEGORIES: readonly ConstraintCategory[] = [
  {
    categoryId: "cat_syn_0001",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "1",
    title: "Design information",
    description: "Information required from the design team before work can proceed.",
    displayOrder: 1,
    state: "ACTIVE",
    nextSequence: 13,
    issuedCount: 12,
    version: 4,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0002",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "2",
    title: "Procurement",
    description: "Long-lead items and subcontract packages.",
    displayOrder: 2,
    state: "ACTIVE",
    nextSequence: 12,
    issuedCount: 11,
    version: 3,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0003",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "3",
    title: "Site access and possession",
    description: "Access, road closures and possession dates.",
    displayOrder: 3,
    state: "ACTIVE",
    nextSequence: 10,
    issuedCount: 9,
    version: 2,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0004",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "4",
    title: "Utilities and diversions",
    description: "Statutory undertaker works.",
    displayOrder: 4,
    state: "ACTIVE",
    nextSequence: 9,
    issuedCount: 8,
    version: 2,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0005",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "5",
    title: "Client decisions",
    description: "Decisions the client must return before a package is fixed.",
    displayOrder: 5,
    state: "ACTIVE",
    nextSequence: 8,
    issuedCount: 7,
    version: 2,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0006",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "6",
    title: "Consents and permits",
    description: "Statutory consents.",
    displayOrder: 6,
    state: "INACTIVE",
    nextSequence: 5,
    issuedCount: 4,
    version: 5,
    prefixLocked: true,
  },
  {
    categoryId: "cat_syn_0007",
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    prefix: "L",
    title: "Legacy log (imported)",
    description: "Rows carried across from the legacy Constraints Log workbook.",
    displayOrder: 7,
    state: "INACTIVE",
    nextSequence: 1,
    issuedCount: 0,
    version: 1,
    prefixLocked: true,
  },
] as const;

function categoryRef(categoryId: string): ConstraintCategoryRef | null {
  const category = CATEGORIES.find((candidate) => candidate.categoryId === categoryId);
  if (!category) return null;
  return { categoryId: category.categoryId, prefix: category.prefix, title: category.title };
}

// --- The record seeds --------------------------------------------------------
//
// One entry per stored record. Every derived flag is written down rather than
// worked out, because that is what makes this a stand-in for a backend and not
// a second implementation of one.

interface Seed {
  readonly n: number;
  readonly code: string | null;
  readonly categoryId: string;
  readonly description: string;
  readonly status: ConstraintLifecycle | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly bic: readonly ConstraintPartyRef[];
  readonly responsible: readonly ConstraintPartyRef[];
  readonly reference: string | null;
  readonly daysElapsed: number | null;
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly needsAttention?: boolean;
  readonly legacy?: boolean;
  readonly sync?: ConstraintSyncState;
  readonly currentUpdate?: string | null;
}

function seed(partial: Seed): Seed {
  return partial;
}

const SEEDS: readonly Seed[] = [
  // Category 1 — Design information.
  seed({ n: 1, code: "1.01", categoryId: "cat_syn_0001", description: "Confirm north abutment reinforcement schedule before the rebar order closes.", status: "IN_PROGRESS", dateIdentified: "2026-05-04", dueDate: "2026-08-28", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_PRINCIPAL], reference: "RFI-0112", daysElapsed: 88, isOverdue: true, isDueSoon: false, inMyCourt: false, currentUpdate: "Design team confirmed a revised schedule is with their checker." }),
  seed({ n: 2, code: "1.02", categoryId: "cat_syn_0001", description: "Issue setting-out drawing for the attenuation basin.", status: "IDENTIFIED", dateIdentified: "2026-06-11", dueDate: "2026-09-11", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_DESIGN_LEAD], reference: "DWG-2201", daysElapsed: 62, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 3, code: "1.03", categoryId: "cat_syn_0001", description: "Resolve clash between drainage run and duct bank at chainage 240.", status: "PENDING", dateIdentified: "2026-06-18", dueDate: "2026-09-09", bic: [PARTY_PRINCIPAL], responsible: [PARTY_DESIGN_LEAD], reference: "CLASH-018", daysElapsed: 57, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 4, code: "1.04", categoryId: "cat_syn_0001", description: "Confirm parapet finish specification.", status: "ON_HOLD", dateIdentified: "2026-04-02", dueDate: "2026-10-30", bic: [PARTY_CLIENT_PM], responsible: [PARTY_DESIGN_LEAD], reference: "SPEC-044", daysElapsed: 134, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 5, code: "1.05", categoryId: "cat_syn_0001", description: "Approve temporary works design for the sheet-piled cofferdam.", status: "IN_PROGRESS", dateIdentified: "2026-07-01", dueDate: "2026-09-08", bic: [PARTY_PRINCIPAL, PARTY_DESIGN_LEAD], responsible: [PARTY_PRINCIPAL], reference: "TW-007", daysElapsed: 45, isOverdue: false, isDueSoon: true, inMyCourt: true, sync: "DB_EXPORT_PENDING" }),
  seed({ n: 6, code: "1.06", categoryId: "cat_syn_0001", description: "Issue revised levels for the southern approach slab.", status: "IDENTIFIED", dateIdentified: "2026-07-14", dueDate: "2026-10-02", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_UNRESOLVED_STRUCTURAL], reference: null, daysElapsed: 36, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 7, code: "1.07", categoryId: "cat_syn_0001", description: "Confirm waterproofing system for the deck.", status: "CLOSED", dateIdentified: "2026-03-09", dueDate: "2026-06-30", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_PRINCIPAL], reference: "SPEC-051", daysElapsed: 113, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 8, code: "1.08", categoryId: "cat_syn_0001", description: "Agree the bearing replacement methodology.", status: "CLOSED", dateIdentified: "2026-02-17", dueDate: "2026-05-22", bic: [PARTY_PRINCIPAL], responsible: [PARTY_DESIGN_LEAD], reference: "METH-003", daysElapsed: 94, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 9, code: "1.09", categoryId: "cat_syn_0001", description: "Duplicate of 1.03 raised by a second discipline.", status: "VOID", dateIdentified: "2026-06-19", dueDate: null, bic: [PARTY_DESIGN_LEAD], responsible: [], reference: null, daysElapsed: 4, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 10, code: "1.10", categoryId: "cat_syn_0001", description: "Confirm the handrail fixing detail at the stair core. Code 1.10 is text and is not 1.1.", status: "IDENTIFIED", dateIdentified: "2026-07-22", dueDate: "2026-11-13", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_DESIGN_LEAD], reference: "DET-1.10", daysElapsed: 28, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 11, code: "1.11", categoryId: "cat_syn_0001", description: "Provide the pile cap reinforcement bending schedule.", status: "IN_PROGRESS", dateIdentified: "2026-07-28", dueDate: "2026-09-10", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_PRINCIPAL], reference: "RFI-0140", daysElapsed: 24, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 12, code: "1.12", categoryId: "cat_syn_0001", description: "Confirm expansion joint type at the east abutment.", status: "IDENTIFIED", dateIdentified: "2026-08-03", dueDate: "2026-12-01", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_DESIGN_LEAD], reference: null, daysElapsed: 20, isOverdue: false, isDueSoon: false, inMyCourt: false }),

  // Category 2 — Procurement.
  seed({ n: 13, code: "2.01", categoryId: "cat_syn_0002", description: "Place the order for precast beams. Code 2.01 is text and is not the number 2.01.", status: "IN_PROGRESS", dateIdentified: "2026-04-20", dueDate: "2026-08-14", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: "PO-4410", daysElapsed: 100, isOverdue: true, isDueSoon: false, inMyCourt: true, sync: "CONFLICT", needsAttention: true }),
  seed({ n: 14, code: "2.02", categoryId: "cat_syn_0002", description: "Award the surfacing subcontract.", status: "PENDING", dateIdentified: "2026-05-19", dueDate: "2026-09-12", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: "PKG-08", daysElapsed: 79, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 15, code: "2.03", categoryId: "cat_syn_0002", description: "Confirm the lead time for the bespoke drainage chambers.", status: "IDENTIFIED", dateIdentified: "2026-06-02", dueDate: "2026-10-16", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 70, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 16, code: "2.04", categoryId: "cat_syn_0002", description: "Agree the concrete supply framework rates.", status: "ON_HOLD", dateIdentified: "2026-03-30", dueDate: "2026-11-27", bic: [PARTY_CLIENT_PM], responsible: [PARTY_PRINCIPAL], reference: "COM-019", daysElapsed: 136, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 17, code: "2.05", categoryId: "cat_syn_0002", description: "Order the parapet units.", status: "IDENTIFIED", dateIdentified: "2026-07-06", dueDate: "2026-09-09", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: "PO-4462", daysElapsed: 40, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 18, code: "2.06", categoryId: "cat_syn_0002", description: "Confirm the traffic management supplier.", status: "IN_PROGRESS", dateIdentified: "2026-07-09", dueDate: "2026-10-09", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 38, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 19, code: "2.07", categoryId: "cat_syn_0002", description: "Close out the temporary bridge hire agreement.", status: "CLOSED", dateIdentified: "2026-01-26", dueDate: "2026-04-30", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: "HIRE-002", daysElapsed: 87, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 20, code: "2.08", categoryId: "cat_syn_0002", description: "Raised in error against the wrong package.", status: "VOID", dateIdentified: "2026-05-08", dueDate: null, bic: [PARTY_PRINCIPAL], responsible: [], reference: null, daysElapsed: 2, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 21, code: "2.09", categoryId: "cat_syn_0002", description: "Confirm the steel fabrication inspection regime.", status: "IDENTIFIED", dateIdentified: "2026-08-05", dueDate: "2026-11-06", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: "QA-014", daysElapsed: 18, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 22, code: "2.10", categoryId: "cat_syn_0002", description: "Order the anti-skid surfacing. Code 2.10 sorts after 2.09 as text.", status: "IDENTIFIED", dateIdentified: "2026-08-10", dueDate: "2026-11-20", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 13, isOverdue: false, isDueSoon: false, inMyCourt: true }),
  seed({ n: 23, code: "2.11", categoryId: "cat_syn_0002", description: "Confirm the disposal contractor for contaminated arisings.", status: "PENDING", dateIdentified: "2026-08-12", dueDate: "2026-09-10", bic: [PARTY_UNRESOLVED_TBC], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 11, isOverdue: false, isDueSoon: true, inMyCourt: false }),

  // Category 3 — Site access and possession.
  seed({ n: 24, code: "3.01", categoryId: "cat_syn_0003", description: "Obtain the road space booking for the beam lift weekend.", status: "IN_PROGRESS", dateIdentified: "2026-05-11", dueDate: "2026-08-21", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "RSB-0091", daysElapsed: 84, isOverdue: true, isDueSoon: false, inMyCourt: false }),
  seed({ n: 25, code: "3.02", categoryId: "cat_syn_0003", description: "Agree the compound extension with the adjacent landowner.", status: "PENDING", dateIdentified: "2026-06-08", dueDate: "2026-09-25", bic: [PARTY_CLIENT_PM], responsible: [PARTY_PRINCIPAL], reference: "LAND-004", daysElapsed: 60, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 26, code: "3.03", categoryId: "cat_syn_0003", description: "Confirm the rail possession dates for the parapet works.", status: "IDENTIFIED", dateIdentified: "2026-06-25", dueDate: "2026-09-11", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "POSS-2026-14", daysElapsed: 51, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 27, code: "3.04", categoryId: "cat_syn_0003", description: "Resolve the pedestrian diversion objection.", status: "ON_HOLD", dateIdentified: "2026-04-14", dueDate: "2026-12-18", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 125, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 28, code: "3.05", categoryId: "cat_syn_0003", description: "Confirm the crane oversail agreement.", status: "IN_PROGRESS", dateIdentified: "2026-07-17", dueDate: "2026-09-09", bic: [PARTY_PRINCIPAL], responsible: [PARTY_PRINCIPAL], reference: "OVS-001", daysElapsed: 33, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 29, code: "3.06", categoryId: "cat_syn_0003", description: "Agree the wheel-wash location with environmental health.", status: "IDENTIFIED", dateIdentified: "2026-08-01", dueDate: "2026-10-23", bic: [PARTY_AUTHORITY], responsible: [PARTY_GROUNDWORKS], reference: null, daysElapsed: 22, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 30, code: "3.07", categoryId: "cat_syn_0003", description: "Close the temporary footway licence.", status: "CLOSED", dateIdentified: "2026-02-03", dueDate: "2026-05-15", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "LIC-0033", daysElapsed: 91, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 31, code: "3.08", categoryId: "cat_syn_0003", description: "Confirm the night-working consent hours.", status: "PENDING", dateIdentified: "2026-08-07", dueDate: "2026-09-12", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "S61-0007", daysElapsed: 16, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 32, code: "3.09", categoryId: "cat_syn_0003", description: "Agree the haul route condition survey scope.", status: "IDENTIFIED", dateIdentified: "2026-08-14", dueDate: "2026-11-02", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 9, isOverdue: false, isDueSoon: false, inMyCourt: true }),

  // Category 4 — Utilities and diversions.
  seed({ n: 33, code: "4.01", categoryId: "cat_syn_0004", description: "Complete the 11kV diversion at the western verge.", status: "IN_PROGRESS", dateIdentified: "2026-03-16", dueDate: "2026-07-31", bic: [PARTY_UTILITY], responsible: [PARTY_PRINCIPAL], reference: "DIV-0102", daysElapsed: 140, isOverdue: true, isDueSoon: false, inMyCourt: false, sync: "DB_EXPORT_PENDING" }),
  seed({ n: 34, code: "4.02", categoryId: "cat_syn_0004", description: "Confirm the water main abandonment method.", status: "PENDING", dateIdentified: "2026-05-26", dueDate: "2026-09-10", bic: [PARTY_UTILITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 73, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 35, code: "4.03", categoryId: "cat_syn_0004", description: "Obtain the gas plant protection agreement.", status: "IDENTIFIED", dateIdentified: "2026-06-30", dueDate: "2026-10-08", bic: [PARTY_UTILITY], responsible: [PARTY_GROUNDWORKS], reference: "GPA-0018", daysElapsed: 46, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 36, code: "4.04", categoryId: "cat_syn_0004", description: "Resolve the unrecorded duct discovered at chainage 90.", status: "IN_PROGRESS", dateIdentified: "2026-07-20", dueDate: "2026-09-08", bic: [PARTY_PRINCIPAL], responsible: [PARTY_UTILITY], reference: null, daysElapsed: 30, isOverdue: false, isDueSoon: true, inMyCourt: true, needsAttention: true, sync: "CONFLICT" }),
  seed({ n: 37, code: "4.05", categoryId: "cat_syn_0004", description: "Confirm the telecoms cable pull dates.", status: "IDENTIFIED", dateIdentified: "2026-08-04", dueDate: "2026-11-14", bic: [PARTY_UTILITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 19, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 38, code: "4.06", categoryId: "cat_syn_0004", description: "Close the street-lighting disconnection.", status: "CLOSED", dateIdentified: "2026-01-14", dueDate: "2026-04-18", bic: [PARTY_UTILITY], responsible: [PARTY_PRINCIPAL], reference: "SL-0044", daysElapsed: 79, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 39, code: "4.07", categoryId: "cat_syn_0004", description: "Confirm the surface water outfall consent conditions.", status: "ON_HOLD", dateIdentified: "2026-05-01", dueDate: "2026-12-04", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 108, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 40, code: "4.08", categoryId: "cat_syn_0004", description: "Agree the utility strike reporting protocol.", status: "IDENTIFIED", dateIdentified: "2026-08-17", dueDate: "2026-10-30", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 6, isOverdue: false, isDueSoon: false, inMyCourt: true }),

  // Category 5 — Client decisions.
  seed({ n: 41, code: "5.01", categoryId: "cat_syn_0005", description: "Client to confirm the parapet colour.", status: "PENDING", dateIdentified: "2026-06-15", dueDate: "2026-09-11", bic: [PARTY_CLIENT_PM], responsible: [PARTY_CLIENT_PM], reference: "DEC-021", daysElapsed: 55, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 42, code: "5.02", categoryId: "cat_syn_0005", description: "Client to accept the revised completion date.", status: "IN_PROGRESS", dateIdentified: "2026-04-27", dueDate: "2026-08-07", bic: [PARTY_CLIENT_PM], responsible: [PARTY_PRINCIPAL], reference: "EOT-002", daysElapsed: 105, isOverdue: true, isDueSoon: false, inMyCourt: false }),
  /**
   * The contract-boundary record. Its due date is years past and the backend
   * says it is not overdue. Any browser that recomputed urgency from the date
   * would contradict this row, which is exactly what it exists to catch.
   * `04_REGISTER_PRODUCT_SPECIFICATION` §6 asks for it by name.
   */
  seed({ n: 43, code: "5.03", categoryId: "cat_syn_0005", description: "Historic due date retained from a superseded programme; the backend does not treat this record as overdue.", status: "ON_HOLD", dateIdentified: "2021-02-09", dueDate: "2021-03-31", bic: [PARTY_CLIENT_PM], responsible: [PARTY_PRINCIPAL], reference: "PROG-OLD-1", daysElapsed: 1841, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 44, code: "5.04", categoryId: "cat_syn_0005", description: "Client to confirm the landscaping scope.", status: "IDENTIFIED", dateIdentified: "2026-07-24", dueDate: "2026-10-16", bic: [PARTY_CLIENT_PM], responsible: [PARTY_CLIENT_PM], reference: null, daysElapsed: 26, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 45, code: "5.05", categoryId: "cat_syn_0005", description: "Client to release the stage 3 payment certificate.", status: "IN_PROGRESS", dateIdentified: "2026-08-06", dueDate: "2026-09-09", bic: [PARTY_PRINCIPAL], responsible: [PARTY_CLIENT_PM], reference: "CERT-003", daysElapsed: 17, isOverdue: false, isDueSoon: true, inMyCourt: true }),
  seed({ n: 46, code: "5.06", categoryId: "cat_syn_0005", description: "Client decision on the alternative deck finish.", status: "CLOSED", dateIdentified: "2026-02-24", dueDate: "2026-05-08", bic: [PARTY_CLIENT_PM], responsible: [PARTY_CLIENT_PM], reference: null, daysElapsed: 73, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 47, code: "5.07", categoryId: "cat_syn_0005", description: "Client to confirm the signage schedule.", status: "IDENTIFIED", dateIdentified: "2026-08-18", dueDate: "2026-11-27", bic: [PARTY_CLIENT_PM], responsible: [PARTY_CLIENT_PM], reference: null, daysElapsed: 5, isOverdue: false, isDueSoon: false, inMyCourt: false }),

  // Category 6 — Consents and permits (an inactive Category with live history).
  seed({ n: 48, code: "6.01", categoryId: "cat_syn_0006", description: "Discharge the pre-commencement planning condition 7.", status: "CLOSED", dateIdentified: "2026-01-08", dueDate: "2026-03-20", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "PLN-C7", daysElapsed: 71, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 49, code: "6.02", categoryId: "cat_syn_0006", description: "Obtain the protected species licence.", status: "IN_PROGRESS", dateIdentified: "2026-03-02", dueDate: "2026-08-19", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "ECO-0009", daysElapsed: 154, isOverdue: true, isDueSoon: false, inMyCourt: false }),
  seed({ n: 50, code: "6.03", categoryId: "cat_syn_0006", description: "Agree the noise monitoring locations.", status: "IDENTIFIED", dateIdentified: "2026-07-11", dueDate: "2026-09-12", bic: [PARTY_AUTHORITY], responsible: [PARTY_GROUNDWORKS], reference: null, daysElapsed: 36, isOverdue: false, isDueSoon: true, inMyCourt: false }),
  seed({ n: 51, code: "6.04", categoryId: "cat_syn_0006", description: "Withdrawn after the consent route changed.", status: "VOID", dateIdentified: "2026-04-09", dueDate: null, bic: [PARTY_AUTHORITY], responsible: [], reference: null, daysElapsed: 12, isOverdue: false, isDueSoon: false, inMyCourt: false }),

  // Category 7 — the legacy import. Unpadded Codes, incomplete records, and a
  // record whose stored lifecycle is null. None of the gaps is filled in here.
  seed({ n: 52, code: "L.1", categoryId: "cat_syn_0007", description: "Legacy row: confirm the drainage invert at manhole 4.", status: "IDENTIFIED", dateIdentified: null, dueDate: null, bic: [PARTY_UNRESOLVED_STRUCTURAL], responsible: [], reference: "log row 12", daysElapsed: null, isOverdue: false, isDueSoon: false, inMyCourt: false, legacy: true, needsAttention: true, sync: "NEVER_SYNCED" }),
  seed({ n: 53, code: "L.10", categoryId: "cat_syn_0007", description: "Legacy row: chase the outstanding kerb detail. Its Code L.10 is a different record from L.1, and sorts between L.1 and L.2 as text.", status: "PENDING", dateIdentified: "2024-11-04", dueDate: null, bic: [PARTY_UNRESOLVED_TBC], responsible: [], reference: "log row 13", daysElapsed: null, isOverdue: false, isDueSoon: false, inMyCourt: false, legacy: true, needsAttention: true, sync: "NEVER_SYNCED" }),
  seed({ n: 54, code: "L.2", categoryId: "cat_syn_0007", description: "Legacy row with no stored lifecycle state at all.", status: null, dateIdentified: null, dueDate: null, bic: [], responsible: [], reference: "log row 14", daysElapsed: null, isOverdue: false, isDueSoon: false, inMyCourt: false, legacy: true, needsAttention: true, sync: "NEVER_SYNCED" }),
  seed({ n: 55, code: "L.15", categoryId: "cat_syn_0007", description: "Legacy row: outstanding as-built information from the previous contractor.", status: "IDENTIFIED", dateIdentified: "2024-09-18", dueDate: "2025-01-31", bic: [PARTY_UNRESOLVED_TBC], responsible: [], reference: "log row 15", daysElapsed: null, isOverdue: true, isDueSoon: false, inMyCourt: false, legacy: true, needsAttention: true, sync: "NEVER_SYNCED" }),

  // Drafts. A Draft has no public Code and never a predicted one.
  seed({ n: 56, code: null, categoryId: "cat_syn_0001", description: "Draft: confirm the movement joint spacing before this is published.", status: "DRAFT", dateIdentified: "2026-08-20", dueDate: null, bic: [PARTY_DESIGN_LEAD], responsible: [], reference: null, daysElapsed: 3, isOverdue: false, isDueSoon: false, inMyCourt: false, sync: "NEVER_SYNCED" }),
  seed({ n: 57, code: null, categoryId: "cat_syn_0002", description: "Draft: scope the additional ground investigation.", status: "DRAFT", dateIdentified: "2026-08-21", dueDate: null, bic: [], responsible: [], reference: null, daysElapsed: 2, isOverdue: false, isDueSoon: false, inMyCourt: false, sync: "NEVER_SYNCED" }),
  seed({ n: 58, code: null, categoryId: "cat_syn_0006", description: "Draft raised against a Category that has since been deactivated; it is not migrated anywhere.", status: "DRAFT", dateIdentified: "2026-08-22", dueDate: null, bic: [], responsible: [], reference: null, daysElapsed: 1, isOverdue: false, isDueSoon: false, inMyCourt: false, sync: "NEVER_SYNCED" }),

  // Tail rows, so a bounded first page and a continuation are both real.
  seed({ n: 59, code: "1.13", categoryId: "cat_syn_0001", description: "Confirm the deck drainage outlet positions.", status: "IDENTIFIED", dateIdentified: "2026-08-19", dueDate: "2026-12-11", bic: [PARTY_DESIGN_LEAD], responsible: [PARTY_DESIGN_LEAD], reference: null, daysElapsed: 4, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 60, code: "2.12", categoryId: "cat_syn_0002", description: "Confirm the bearing supplier's factory acceptance date.", status: "IDENTIFIED", dateIdentified: "2026-08-19", dueDate: "2026-12-18", bic: [PARTY_GROUNDWORKS], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 4, isOverdue: false, isDueSoon: false, inMyCourt: true }),
  seed({ n: 61, code: "3.10", categoryId: "cat_syn_0003", description: "Confirm the diversion signage approval. Code 3.10 sorts after 3.09 as text.", status: "IDENTIFIED", dateIdentified: "2026-08-20", dueDate: "2026-12-04", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 3, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 62, code: "4.09", categoryId: "cat_syn_0004", description: "Confirm the substation handover date.", status: "IDENTIFIED", dateIdentified: "2026-08-20", dueDate: "2027-01-15", bic: [PARTY_UTILITY], responsible: [PARTY_PRINCIPAL], reference: null, daysElapsed: 3, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 63, code: "5.08", categoryId: "cat_syn_0005", description: "Client to confirm the maintenance access arrangement.", status: "IDENTIFIED", dateIdentified: "2026-08-21", dueDate: "2027-01-29", bic: [PARTY_CLIENT_PM], responsible: [PARTY_CLIENT_PM], reference: null, daysElapsed: 2, isOverdue: false, isDueSoon: false, inMyCourt: false }),
  seed({ n: 64, code: "6.05", categoryId: "cat_syn_0006", description: "Successor raised when 6.02 was closed with a follow-up.", status: "IDENTIFIED", dateIdentified: "2026-08-22", dueDate: "2026-11-30", bic: [PARTY_AUTHORITY], responsible: [PARTY_PRINCIPAL], reference: "ECO-0010", daysElapsed: 1, isOverdue: false, isDueSoon: false, inMyCourt: false }),
] as const;

/** `cst_syn_0001` … `cst_syn_0064`. Stable row identity, never a display value. */
function constraintId(n: number): string {
  return `cst_syn_${String(n).padStart(4, "0")}`;
}

function groupKeysFor(entry: Omit<ConstraintListEntry, "groupKeys">): readonly string[] {
  // Every grouping's membership, precomputed the way a server returns it: one
  // key per grouping dimension, and a party grouping contributing one key per
  // party reference it actually has. A row is never duplicated by this.
  const keys: string[] = [];
  if (entry.category) keys.push(`category:${entry.category.categoryId}`);
  keys.push(`status:${entry.status ?? "unavailable"}`);
  for (const party of entry.bic) keys.push(`bic:${party.partyRefId ?? "unresolved"}`);
  for (const party of entry.responsible) keys.push(`responsible:${party.partyRefId ?? "unresolved"}`);
  return keys;
}

function toEntry(item: Seed): ConstraintListEntry {
  const base = {
    constraintId: constraintId(item.n),
    projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
    constraintCode: item.code,
    description: item.description,
    category: categoryRef(item.categoryId),
    status: item.status,
    dateIdentified: item.dateIdentified,
    dueDate: item.dueDate,
    bic: item.bic,
    responsible: item.responsible,
    reference: item.reference,
    daysElapsed: item.daysElapsed,
    version: 1 + (item.n % 5),
    updatedAt: `2026-08-${String(1 + (item.n % 22)).padStart(2, "0")}T09:${String(item.n % 60).padStart(2, "0")}:00Z`,
    isOverdue: item.isOverdue,
    isDueSoon: item.isDueSoon,
    inMyCourt: item.inMyCourt,
    recordQuality: (item.legacy ? "LEGACY_INCOMPLETE" : "NORMAL") as ConstraintListEntry["recordQuality"],
    needsAttention: item.needsAttention ?? item.legacy ?? false,
    syncState: item.sync ?? "IN_SYNC",
  } satisfies Omit<ConstraintListEntry, "groupKeys">;
  return { ...base, groupKeys: groupKeysFor(base) };
}

const ENTRIES: readonly ConstraintListEntry[] = SEEDS.map(toEntry);

/**
 * One row belonging to the *other* Project.
 *
 * It exists so "no cross-Project leakage" is a claim a test can falsify rather
 * than an absence nobody checked. Nothing in the first Project's corpus refers
 * to it and the read plane below never returns it for `prj_syn_0001`.
 */
const SECOND_PROJECT_ENTRY: ConstraintListEntry = {
  constraintId: "cst_syn_9001",
  projectId: SYNTHETIC_SECOND_PROJECT_ID,
  constraintCode: "1.01",
  description: "Northgate Depot: confirm the loading bay levels.",
  category: { categoryId: "cat_syn_9001", prefix: "1", title: "Design information" },
  status: "IDENTIFIED",
  dateIdentified: "2026-07-02",
  dueDate: "2026-09-30",
  bic: [PARTY_DESIGN_LEAD],
  responsible: [PARTY_PRINCIPAL],
  reference: null,
  daysElapsed: 52,
  version: 1,
  updatedAt: "2026-08-18T11:00:00Z",
  isOverdue: false,
  isDueSoon: false,
  inMyCourt: false,
  recordQuality: "NORMAL",
  needsAttention: false,
  syncState: "IN_SYNC",
  groupKeys: ["category:cat_syn_9001", "status:IDENTIFIED", "bic:ent_aaaaaaaa11111111", "responsible:principal"],
};

// --- Detail, relationships, evidence and history -----------------------------

const RELATIONSHIPS: Readonly<Record<string, readonly ConstraintRelationship[]>> = {
  [constraintId(49)]: [
    {
      relationshipId: "rel_syn_0001",
      relationshipType: "CLOSED_WITH_FOLLOW_UP",
      direction: "OUTGOING",
      relatedConstraintId: constraintId(64),
      relatedConstraintCode: "6.05",
      relatedStatus: "IDENTIFIED",
    },
  ],
  [constraintId(64)]: [
    {
      relationshipId: "rel_syn_0001",
      relationshipType: "CLOSED_WITH_FOLLOW_UP",
      direction: "INCOMING",
      relatedConstraintId: constraintId(49),
      relatedConstraintCode: "6.02",
      relatedStatus: "IN_PROGRESS",
    },
  ],
  [constraintId(3)]: [
    {
      relationshipId: "rel_syn_0002",
      relationshipType: "DUPLICATE_OF",
      direction: "INCOMING",
      relatedConstraintId: constraintId(9),
      relatedConstraintCode: "1.09",
      relatedStatus: "VOID",
    },
  ],
};

const EVIDENCE: Readonly<Record<string, readonly ConstraintEvidenceLink[]>> = {
  [constraintId(1)]: [
    {
      evidenceLinkId: "evl_syn_0001",
      evidenceKind: "rfi_response",
      evidenceRef: "https://synthetic.example/rfi/0112",
      role: "supporting",
      isSafeUrl: true,
    },
    {
      evidenceLinkId: "evl_syn_0002",
      evidenceKind: "workbook_row",
      evidenceRef: "Constraints Log 2026-Q2, row 41",
      role: "origin",
      isSafeUrl: false,
    },
  ],
  [constraintId(13)]: [
    {
      evidenceLinkId: "evl_syn_0003",
      evidenceKind: "purchase_order",
      evidenceRef: "https://synthetic.example/po/4410",
      role: "supporting",
      isSafeUrl: true,
    },
  ],
  [constraintId(55)]: [
    {
      evidenceLinkId: "evl_syn_0004",
      evidenceKind: "workbook_row",
      evidenceRef: "Legacy Constraints Log, row 15",
      role: "origin",
      isSafeUrl: false,
    },
  ],
};

function historyFor(entry: ConstraintListEntry): readonly ConstraintHistoryEntry[] {
  const created: ConstraintHistoryEntry = {
    historyId: `hst_${entry.constraintId}_1`,
    operation: "CREATE",
    actor: entry.recordQuality === "LEGACY_INCOMPLETE" ? "SYSTEM" : "PRINCIPAL",
    outcome: "APPLIED",
    beforeVersion: 0,
    afterVersion: 1,
    occurredAt: `${entry.dateIdentified ?? "2024-09-01"}T08:15:00Z`,
    revisionId: `rev_${entry.constraintId}_1`,
    safeFailureReason: null,
    provenance:
      entry.recordQuality === "LEGACY_INCOMPLETE"
        ? "Imported from the legacy Constraints Log workbook."
        : null,
  };
  if (entry.status === "DRAFT") return [created];

  const published: ConstraintHistoryEntry = {
    historyId: `hst_${entry.constraintId}_2`,
    operation: "PUBLISH",
    actor: "PRINCIPAL",
    outcome: "APPLIED",
    beforeVersion: 1,
    afterVersion: 2,
    occurredAt: `${entry.dateIdentified ?? "2024-09-01"}T08:40:00Z`,
    revisionId: `rev_${entry.constraintId}_2`,
    safeFailureReason: null,
    provenance: null,
  };
  const entries: ConstraintHistoryEntry[] = [created, published];

  if (entry.status === "CLOSED") {
    entries.push({
      historyId: `hst_${entry.constraintId}_3`,
      operation: "CLOSE",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: 2,
      afterVersion: 3,
      occurredAt: entry.updatedAt,
      revisionId: `rev_${entry.constraintId}_3`,
      safeFailureReason: null,
      provenance: null,
    });
  }
  if (entry.status === "VOID") {
    entries.push({
      historyId: `hst_${entry.constraintId}_3`,
      operation: "VOID",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: 2,
      afterVersion: 3,
      occurredAt: entry.updatedAt,
      revisionId: `rev_${entry.constraintId}_3`,
      safeFailureReason: null,
      provenance: null,
    });
  }
  if (entry.status === "IN_PROGRESS" || entry.status === "ON_HOLD" || entry.status === "PENDING") {
    entries.push({
      historyId: `hst_${entry.constraintId}_3`,
      operation: "TRANSITION",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: 2,
      afterVersion: 3,
      occurredAt: entry.updatedAt,
      revisionId: `rev_${entry.constraintId}_3`,
      safeFailureReason: null,
      provenance: null,
    });
  }
  return entries.reverse();
}

function detailFor(entry: ConstraintListEntry): ConstraintView {
  const legacy = entry.recordQuality === "LEGACY_INCOMPLETE";
  const seedRecord = SEEDS.find((candidate) => constraintId(candidate.n) === entry.constraintId);
  return {
    constraintId: entry.constraintId,
    projectId: entry.projectId,
    constraintCode: entry.constraintCode,
    description: entry.description,
    category: entry.category,
    status: entry.status,
    dateIdentified: entry.dateIdentified,
    dueDate: entry.dueDate,
    bic: entry.bic,
    responsible: entry.responsible,
    reference: entry.reference,
    daysElapsed: entry.daysElapsed,
    version: entry.version,
    createdAt: `${entry.dateIdentified ?? "2024-09-01"}T08:15:00Z`,
    updatedAt: entry.updatedAt,
    isOverdue: entry.isOverdue,
    isDueSoon: entry.isDueSoon,
    inMyCourt: entry.inMyCourt,
    recordQuality: entry.recordQuality,
    needsAttention: entry.needsAttention,
    // Reasons and missing fields are backend-published. A NORMAL record that
    // needs attention for a sync conflict says so; a legacy record names only
    // the fields the backend recorded as missing, and nothing else is guessed.
    needsAttentionReasons: legacy
      ? ["LEGACY_INCOMPLETE"]
      : entry.syncState === "CONFLICT"
        ? ["OPEN_SYNC_CONFLICT"]
        : [],
    missingFields: legacy
      ? entry.constraintCode === null
        ? ["constraint_code", "date_identified", "due_date", "bic"]
        : ["date_identified", "due_date", "bic"]
      : [],
    isPublished: entry.status !== "DRAFT",
    publishedAt: entry.status === "DRAFT" ? null : `${entry.dateIdentified ?? "2024-09-01"}T08:40:00Z`,
    currentUpdate: seedRecord?.currentUpdate ?? null,
    completion:
      entry.status === "CLOSED"
        ? legacy
          ? { completionDate: null, closureCommentary: null }
          : {
              completionDate: entry.updatedAt.slice(0, 10),
              closureCommentary: "Resolved and agreed at the weekly progress meeting.",
            }
        : null,
    void:
      entry.status === "VOID"
        ? { voidedDate: entry.updatedAt.slice(0, 10), voidReason: "Raised in duplicate." }
        : null,
    sync: {
      state: entry.syncState,
      lastVerifiedAt: entry.syncState === "NEVER_SYNCED" ? null : "2026-08-22T06:00:00Z",
      conflictCount: entry.syncState === "CONFLICT" ? 1 : 0,
    },
    relationships: RELATIONSHIPS[entry.constraintId] ?? [],
    evidenceLinks: EVIDENCE[entry.constraintId] ?? [],
  };
}

// --- The Overview ------------------------------------------------------------
//
// Stored, not tallied. These are what the Project's own calendar produced at
// `asOf`; a Register page is bounded and cannot reconstruct them.

const OVERVIEW: ConstraintOverview = {
  projectId: SYNTHETIC_CONSTRAINT_PROJECT_ID,
  projectToday: "2026-08-24",
  projectTimezone: "Europe/London",
  totalOpen: 41,
  overdue: 6,
  dueSoon: 12,
  dueSoonThrough: "2026-09-02",
  averageOpenAgeBusinessDays: 38.4,
  inMyCourt: 11,
  onHold: 5,
  recentlyChanged: 9,
  recentlyClosed: 3,
  draft: 3,
  needsAttention: 6,
  syncHealth: {
    state: "CONFLICT",
    openConflictCount: 2,
    lastVerifiedAt: "2026-08-22T06:00:00Z",
  },
  asOf: "2026-08-24T05:30:00Z",
};

/** Open counts per Category, as the backend grouped them. Not a client tally. */
const CATEGORY_OPEN_COUNTS: readonly ConstraintCategoryOpenCount[] = [
  { categoryId: "cat_syn_0001", prefix: "1", title: "Design information", openCount: 9 },
  { categoryId: "cat_syn_0002", prefix: "2", title: "Procurement", openCount: 9 },
  { categoryId: "cat_syn_0003", prefix: "3", title: "Site access and possession", openCount: 8 },
  { categoryId: "cat_syn_0004", prefix: "4", title: "Utilities and diversions", openCount: 7 },
  { categoryId: "cat_syn_0005", prefix: "5", title: "Client decisions", openCount: 6 },
  { categoryId: "cat_syn_0006", prefix: "6", title: "Consents and permits", openCount: 2 },
] as const;

// --- The workspace a read returns --------------------------------------------

export interface ConstraintWorkspaceFixture {
  readonly project: ConstraintFixtureProject;
  readonly overview: ConstraintOverview;
  readonly categories: readonly ConstraintCategory[];
  readonly categoryOpenCounts: readonly ConstraintCategoryOpenCount[];
  readonly entries: readonly ConstraintListEntry[];
  readonly details: Readonly<Record<string, ConstraintView>>;
  readonly history: Readonly<Record<string, readonly ConstraintHistoryEntry[]>>;
  readonly partyOptions: readonly ConstraintPartyRef[];
  /** The identifiers a detail read deliberately refuses, so the Inspector's
   *  own unavailable state is reachable without breaking the Register. */
  readonly unreadableDetailIds: readonly string[];
}

/**
 * The whole synthetic read plane for one Project.
 *
 * Refuses outright unless the deployment enabled the synthetic provider, and
 * returns `null` for a Project this corpus does not describe — which is a
 * not-found answer the route can render, not an empty Project.
 */
export function syntheticConstraintWorkspace(
  projectId: string,
): ConstraintWorkspaceFixture | null {
  requireSyntheticProvider();
  const project = SYNTHETIC_CONSTRAINT_PROJECTS.find(
    (candidate) => candidate.projectId === projectId,
  );
  if (!project) return null;

  const entries =
    projectId === SYNTHETIC_CONSTRAINT_PROJECT_ID ? ENTRIES : [SECOND_PROJECT_ENTRY];

  const details: Record<string, ConstraintView> = {};
  const history: Record<string, readonly ConstraintHistoryEntry[]> = {};
  for (const entry of entries) {
    details[entry.constraintId] = detailFor(entry);
    history[entry.constraintId] = historyFor(entry);
  }

  if (projectId !== SYNTHETIC_CONSTRAINT_PROJECT_ID) {
    return {
      project,
      overview: { ...OVERVIEW, projectId, totalOpen: 1, overdue: 0, dueSoon: 0, inMyCourt: 0, onHold: 0, recentlyChanged: 1, recentlyClosed: 0, draft: 0, needsAttention: 0 },
      categories: [],
      categoryOpenCounts: [
        { categoryId: "cat_syn_9001", prefix: "1", title: "Design information", openCount: 1 },
      ],
      entries,
      details,
      history,
      partyOptions: SYNTHETIC_PARTY_OPTIONS,
      unreadableDetailIds: [],
    };
  }

  return {
    project,
    overview: OVERVIEW,
    categories: CATEGORIES,
    categoryOpenCounts: CATEGORY_OPEN_COUNTS,
    entries,
    details,
    history,
    partyOptions: SYNTHETIC_PARTY_OPTIONS,
    // 5.03 is the record whose detail read fails. The Register keeps it; the
    // Inspector states that the detail could not be read (`CM-FE-AC-029`, and
    // `08_INSPECTOR_HISTORY_AND_EVIDENCE` §3).
    unreadableDetailIds: [constraintId(43)],
  };
}

/** Every Project this corpus can serve. Used by the Project selector. */
export function syntheticConstraintProjects(): readonly ConstraintFixtureProject[] {
  requireSyntheticProvider();
  return SYNTHETIC_CONSTRAINT_PROJECTS;
}
