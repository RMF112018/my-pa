/**
 * Capability decoder registry. Exactly the GatewayCapability keys in gateway.json.
 *
 * Workers C and D replace files under `capabilities/` only. This module wires
 * the imports so those workers do not need to edit the registry.
 */
import { decodeCapabilitiesGet } from "./capabilities/capabilities.get";
import { decodeKnowledgeSearch } from "./capabilities/knowledge.search";
import { decodeKnowledgeRead } from "./capabilities/knowledge.read";
import { decodeKnowledgeReveal } from "./capabilities/knowledge.reveal";
import { decodeCaptureCreate } from "./capabilities/capture.create";
import { decodeCaptureList } from "./capabilities/capture.list";
import { decodeCaptureRead } from "./capabilities/capture.read";
import { decodeCaptureSearch } from "./capabilities/capture.search";
import { decodeReviewList } from "./capabilities/review.list";
import { decodeReviewDecide } from "./capabilities/review.decide";
import { decodeContinuityPulse } from "./capabilities/continuity.pulse";
import { decodeContinuitySituations } from "./capabilities/continuity.situations";
import { decodeContinuityProjects } from "./capabilities/continuity.projects";
import { decodeTasksRead } from "./capabilities/tasks.read";
import { decodeTasksList } from "./capabilities/tasks.list";
import { decodeTasksSearch } from "./capabilities/tasks.search";
import { decodeTasksHistory } from "./capabilities/tasks.history";
import { decodeTasksCreate } from "./capabilities/tasks.create";
import { decodeTasksUpdate } from "./capabilities/tasks.update";
import { decodeTasksTransition } from "./capabilities/tasks.transition";
import { decodeTasksBulkPreview } from "./capabilities/tasks.bulk_preview";
import { decodeTasksBulkConfirm } from "./capabilities/tasks.bulk_confirm";
import { decodeCommitmentsRead } from "./capabilities/commitments.read";
import { decodeCommitmentsList } from "./capabilities/commitments.list";
import { decodeCommitmentsSearch } from "./capabilities/commitments.search";
import { decodeCommitmentsHistory } from "./capabilities/commitments.history";
import { decodeCommitmentsWaitingOn } from "./capabilities/commitments.waiting_on";
import { decodeCommitmentsCreate } from "./capabilities/commitments.create";
import { decodeCommitmentsUpdate } from "./capabilities/commitments.update";
import { decodeCommitmentsClose } from "./capabilities/commitments.close";
import { decodeReportsRead } from "./capabilities/reports.read";
import { decodeReportsLatest } from "./capabilities/reports.latest";
import { decodeReportsList } from "./capabilities/reports.list";
import { decodeReportsSearch } from "./capabilities/reports.search";
import { decodeReportsResolveSet } from "./capabilities/reports.resolve_set";
import { decodeEntitiesSearch } from "./capabilities/entities.search";
import { decodeEntitiesGet } from "./capabilities/entities.get";
import { decodeEntitiesResolve } from "./capabilities/entities.resolve";
import { decodeEntitiesContext } from "./capabilities/entities.context";
import { decodeEntitiesRelationships } from "./capabilities/entities.relationships";
import { decodeEntitiesRelationshipsCreate } from "./capabilities/entities.relationships.create";
import { decodeEntitiesRelationshipsRevise } from "./capabilities/entities.relationships.revise";
import { decodeEntitiesRelationshipsEnd } from "./capabilities/entities.relationships.end";
import { decodeEntitiesGraph } from "./capabilities/entities.graph";
import { decodeEntitiesUnresolvedMentions } from "./capabilities/entities.unresolved_mentions";
import { decodeEntitiesIdentifiersList } from "./capabilities/entities.identifiers.list";
import { decodeEntitiesAliasesList } from "./capabilities/entities.aliases.list";
import { decodeEntitiesAssignmentsList } from "./capabilities/entities.assignments.list";
import { decodeEntitiesObservationsList } from "./capabilities/entities.observations.list";
import { decodeEntitiesIdentityHistory } from "./capabilities/entities.identity_history";
import { decodeEntitiesProfile } from "./capabilities/entities.profile";
import { decodeEntitiesNamesList } from "./capabilities/entities.names.list";
import { decodeEntitiesAddressesList } from "./capabilities/entities.addresses.list";
import { decodeEntitiesCommunicationList } from "./capabilities/entities.communication.list";
import { decodeEntitiesParticipationsList } from "./capabilities/entities.participations.list";
import { decodeCanvasWorkspaceGet } from "./capabilities/canvas.workspace.get";
import { decodeCanvasWorkspacePut } from "./capabilities/canvas.workspace.put";
import type { CapabilityResults, Decoder, GatewayCapability } from "./types";

export type { CapabilityResults, DecodeResult, Decoder } from "./types";
export type { DecodedDisclosure } from "./disclosure";
export { decodeDisclosure } from "./disclosure";
export { decodeEnvelope } from "./envelope";
export { decodeProblem } from "./problem";

export const DECODERS = {
  "capabilities.get": decodeCapabilitiesGet,
  "knowledge.search": decodeKnowledgeSearch,
  "knowledge.read": decodeKnowledgeRead,
  "knowledge.reveal": decodeKnowledgeReveal,
  "capture.create": decodeCaptureCreate,
  "capture.list": decodeCaptureList,
  "capture.read": decodeCaptureRead,
  "capture.search": decodeCaptureSearch,
  "review.list": decodeReviewList,
  "review.decide": decodeReviewDecide,
  "continuity.pulse": decodeContinuityPulse,
  "continuity.situations": decodeContinuitySituations,
  "continuity.projects": decodeContinuityProjects,
  "tasks.read": decodeTasksRead,
  "tasks.list": decodeTasksList,
  "tasks.search": decodeTasksSearch,
  "tasks.history": decodeTasksHistory,
  "tasks.create": decodeTasksCreate,
  "tasks.update": decodeTasksUpdate,
  "tasks.transition": decodeTasksTransition,
  "tasks.bulk_preview": decodeTasksBulkPreview,
  "tasks.bulk_confirm": decodeTasksBulkConfirm,
  "commitments.read": decodeCommitmentsRead,
  "commitments.list": decodeCommitmentsList,
  "commitments.search": decodeCommitmentsSearch,
  "commitments.history": decodeCommitmentsHistory,
  "commitments.waiting_on": decodeCommitmentsWaitingOn,
  "commitments.create": decodeCommitmentsCreate,
  "commitments.update": decodeCommitmentsUpdate,
  "commitments.close": decodeCommitmentsClose,
  "reports.read": decodeReportsRead,
  "reports.latest": decodeReportsLatest,
  "reports.list": decodeReportsList,
  "reports.search": decodeReportsSearch,
  "reports.resolve_set": decodeReportsResolveSet,
  "entities.search": decodeEntitiesSearch,
  "entities.get": decodeEntitiesGet,
  "entities.resolve": decodeEntitiesResolve,
  "entities.context": decodeEntitiesContext,
  "entities.relationships": decodeEntitiesRelationships,
  "entities.relationships.create": decodeEntitiesRelationshipsCreate,
  "entities.relationships.revise": decodeEntitiesRelationshipsRevise,
  "entities.relationships.end": decodeEntitiesRelationshipsEnd,
  "entities.graph": decodeEntitiesGraph,
  "entities.unresolved_mentions": decodeEntitiesUnresolvedMentions,
  "entities.identifiers.list": decodeEntitiesIdentifiersList,
  "entities.aliases.list": decodeEntitiesAliasesList,
  "entities.assignments.list": decodeEntitiesAssignmentsList,
  "entities.observations.list": decodeEntitiesObservationsList,
  "entities.identity_history": decodeEntitiesIdentityHistory,
  "entities.profile": decodeEntitiesProfile,
  "entities.names.list": decodeEntitiesNamesList,
  "entities.addresses.list": decodeEntitiesAddressesList,
  "entities.communication.list": decodeEntitiesCommunicationList,
  "entities.participations.list": decodeEntitiesParticipationsList,
  "canvas.workspace.get": decodeCanvasWorkspaceGet,
  "canvas.workspace.put": decodeCanvasWorkspacePut,
} satisfies { [K in GatewayCapability]: Decoder<CapabilityResults[K]> };

/**
 * Registry lookup that preserves the capability's decoded result type.
 *
 * The assertion is the registry map, not network data. Callers still pass
 * `unknown` into the selected decoder.
 */
export function decodeCapability<C extends GatewayCapability>(
  capability: C,
  input: unknown,
): import("./primitives").DecodeResult<CapabilityResults[C]> {
  return (DECODERS[capability] as Decoder<CapabilityResults[C]>)(input);
}
