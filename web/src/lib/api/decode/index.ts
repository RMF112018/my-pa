/**
 * Capability decoder registry. Exactly the 29 GatewayCapability keys.
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
import type { Decoder, GatewayCapability } from "./types";

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
} satisfies Record<GatewayCapability, Decoder<unknown>>;
