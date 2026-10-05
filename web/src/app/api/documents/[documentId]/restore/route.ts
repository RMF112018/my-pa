import type { NextRequest } from "next/server";
import {
  invalidWorkRequest,
  isCanonicalId,
  workPost,
} from "@/lib/api/work-route";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ documentId: string }> },
) {
  const { documentId } = await context.params;
  if (!isCanonicalId(documentId, "mdoc")) {
    return invalidWorkRequest("documentId is malformed");
  }
  return workPost(request, "document-restore", "documents.restore", {}, {
    document_id: documentId,
  }, { strictQuery: true, bodyOptional: true });
}
