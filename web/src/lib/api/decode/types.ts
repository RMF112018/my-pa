/**
 * Decoder contracts for the BFF capability registry.
 *
 * `CapabilityResults` is the admitted capability → runtime-decoded result map.
 * A placeholder `unknown` per key is forbidden: that would re-open generic
 * success authority after `invokeGateway`.
 */
import contract from "@/contracts/gateway.json";
import type { CanvasWorkspaceGetResult } from "./capabilities/canvas.workspace.get";
import type { CanvasWorkspacePutResult } from "./capabilities/canvas.workspace.put";
import type { CapabilitiesGetResult } from "./capabilities/capabilities.get";
import type { CaptureCreateResult } from "./capabilities/capture.create";
import type { CaptureListResult } from "./capabilities/capture.list";
import type { CaptureReadResult } from "./capabilities/capture.read";
import type { CaptureSearchResult } from "./capabilities/capture.search";
import type { CommitmentsCloseResult } from "./capabilities/commitments.close";
import type { CommitmentsCreateResult } from "./capabilities/commitments.create";
import type { CommitmentsHistoryResult } from "./capabilities/commitments.history";
import type { CommitmentsListResult } from "./capabilities/commitments.list";
import type { CommitmentsReadResult } from "./capabilities/commitments.read";
import type { CommitmentsSearchResult } from "./capabilities/commitments.search";
import type { CommitmentsUpdateResult } from "./capabilities/commitments.update";
import type { CommitmentsWaitingOnResult } from "./capabilities/commitments.waiting_on";
import type { ContinuityProjectsResult } from "./capabilities/continuity.projects";
import type { ContinuityPulseResult } from "./capabilities/continuity.pulse";
import type { ContinuitySituationsResult } from "./capabilities/continuity.situations";
import type { EntitiesAddressesListResult } from "./capabilities/entities.addresses.list";
import type { EntitiesAliasesListResult } from "./capabilities/entities.aliases.list";
import type { EntitiesAssignmentsListResult } from "./capabilities/entities.assignments.list";
import type { EntitiesCommunicationListResult } from "./capabilities/entities.communication.list";
import type { EntityContextResult } from "./capabilities/entities.context";
import type { EntityGetResult } from "./capabilities/entities.get";
import type { EntitiesGraphResult } from "./capabilities/entities.graph";
import type { EntitiesIdentifiersListResult } from "./capabilities/entities.identifiers.list";
import type { EntitiesIdentityHistoryResult } from "./capabilities/entities.identity_history";
import type { EntitiesNamesListResult } from "./capabilities/entities.names.list";
import type { EntitiesObservationsListResult } from "./capabilities/entities.observations.list";
import type { EntitiesParticipationsListResult } from "./capabilities/entities.participations.list";
import type { EntityProfileResult } from "./capabilities/entities.profile";
import type { EntitiesRelationshipsResult } from "./capabilities/entities.relationships";
import type { EntitiesRelationshipsCreateResult } from "./capabilities/entities.relationships.create";
import type { EntitiesRelationshipsEndResult } from "./capabilities/entities.relationships.end";
import type { EntitiesRelationshipsReviseResult } from "./capabilities/entities.relationships.revise";
import type { EntityResolveResult } from "./capabilities/entities.resolve";
import type { EntitySearchResult } from "./capabilities/entities.search";
import type { EntitiesUnresolvedMentionsResult } from "./capabilities/entities.unresolved_mentions";
import type { KnowledgeReadResult } from "./capabilities/knowledge.read";
import type { KnowledgeRevealResult } from "./capabilities/knowledge.reveal";
import type { KnowledgeSearchResult } from "./capabilities/knowledge.search";
import type { ReportsLatestResult } from "./capabilities/reports.latest";
import type { ReportsListResult } from "./capabilities/reports.list";
import type { ReportsReadResult } from "./capabilities/reports.read";
import type { ReportsResolveSetResult } from "./capabilities/reports.resolve_set";
import type { ReportsSearchResult } from "./capabilities/reports.search";
import type { ReviewDecideResult } from "./capabilities/review.decide";
import type { ReviewListResult } from "./capabilities/review.list";
import type { TasksBulkConfirmResult } from "./capabilities/tasks.bulk_confirm";
import type { TasksBulkPreviewResult } from "./capabilities/tasks.bulk_preview";
import type { TasksCreateResult } from "./capabilities/tasks.create";
import type { TasksHistoryResult } from "./capabilities/tasks.history";
import type { TasksListResult } from "./capabilities/tasks.list";
import type { TasksReadResult } from "./capabilities/tasks.read";
import type { TasksSearchResult } from "./capabilities/tasks.search";
import type { TasksTransitionResult } from "./capabilities/tasks.transition";
import type { TasksUpdateResult } from "./capabilities/tasks.update";
import type { DecodeResult } from "./primitives";

export type { DecodeResult } from "./primitives";

export type Decoder<T> = (input: unknown) => DecodeResult<T>;

/** Same keys as `gateway.json`; kept here so the registry does not import `gateway.ts`. */
export type GatewayCapability = keyof typeof contract.capabilities;

export type CapabilityResults = {
  readonly "canvas.workspace.get": CanvasWorkspaceGetResult;
  readonly "canvas.workspace.put": CanvasWorkspacePutResult;
  readonly "capabilities.get": CapabilitiesGetResult;
  readonly "capture.create": CaptureCreateResult;
  readonly "capture.list": CaptureListResult;
  readonly "capture.read": CaptureReadResult;
  readonly "capture.search": CaptureSearchResult;
  readonly "commitments.close": CommitmentsCloseResult;
  readonly "commitments.create": CommitmentsCreateResult;
  readonly "commitments.history": CommitmentsHistoryResult;
  readonly "commitments.list": CommitmentsListResult;
  readonly "commitments.read": CommitmentsReadResult;
  readonly "commitments.search": CommitmentsSearchResult;
  readonly "commitments.update": CommitmentsUpdateResult;
  readonly "commitments.waiting_on": CommitmentsWaitingOnResult;
  readonly "continuity.projects": ContinuityProjectsResult;
  readonly "continuity.pulse": ContinuityPulseResult;
  readonly "continuity.situations": ContinuitySituationsResult;
  readonly "entities.addresses.list": EntitiesAddressesListResult;
  readonly "entities.aliases.list": EntitiesAliasesListResult;
  readonly "entities.assignments.list": EntitiesAssignmentsListResult;
  readonly "entities.communication.list": EntitiesCommunicationListResult;
  readonly "entities.context": EntityContextResult;
  readonly "entities.get": EntityGetResult;
  readonly "entities.graph": EntitiesGraphResult;
  readonly "entities.identifiers.list": EntitiesIdentifiersListResult;
  readonly "entities.identity_history": EntitiesIdentityHistoryResult;
  readonly "entities.names.list": EntitiesNamesListResult;
  readonly "entities.observations.list": EntitiesObservationsListResult;
  readonly "entities.participations.list": EntitiesParticipationsListResult;
  readonly "entities.profile": EntityProfileResult;
  readonly "entities.relationships": EntitiesRelationshipsResult;
  readonly "entities.relationships.create": EntitiesRelationshipsCreateResult;
  readonly "entities.relationships.end": EntitiesRelationshipsEndResult;
  readonly "entities.relationships.revise": EntitiesRelationshipsReviseResult;
  readonly "entities.resolve": EntityResolveResult;
  readonly "entities.search": EntitySearchResult;
  readonly "entities.unresolved_mentions": EntitiesUnresolvedMentionsResult;
  readonly "knowledge.read": KnowledgeReadResult;
  readonly "knowledge.reveal": KnowledgeRevealResult;
  readonly "knowledge.search": KnowledgeSearchResult;
  readonly "reports.latest": ReportsLatestResult;
  readonly "reports.list": ReportsListResult;
  readonly "reports.read": ReportsReadResult;
  readonly "reports.resolve_set": ReportsResolveSetResult;
  readonly "reports.search": ReportsSearchResult;
  readonly "review.decide": ReviewDecideResult;
  readonly "review.list": ReviewListResult;
  readonly "tasks.bulk_confirm": TasksBulkConfirmResult;
  readonly "tasks.bulk_preview": TasksBulkPreviewResult;
  readonly "tasks.create": TasksCreateResult;
  readonly "tasks.history": TasksHistoryResult;
  readonly "tasks.list": TasksListResult;
  readonly "tasks.read": TasksReadResult;
  readonly "tasks.search": TasksSearchResult;
  readonly "tasks.transition": TasksTransitionResult;
  readonly "tasks.update": TasksUpdateResult;
};

type IsExactlyUnknown<T> = unknown extends T ? ([T] extends [unknown] ? true : false) : false;

type UnknownResultKeys = {
  [K in GatewayCapability]: IsExactlyUnknown<CapabilityResults[K]> extends true ? K : never;
}[GatewayCapability];

type AssertNoUnknownCapabilityResults = [UnknownResultKeys] extends [never]
  ? true
  : UnknownResultKeys;

const _capabilityResultsAreConcrete: AssertNoUnknownCapabilityResults = true;
void _capabilityResultsAreConcrete;
