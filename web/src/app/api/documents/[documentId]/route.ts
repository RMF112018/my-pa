import type { NextRequest } from "next/server";
import type { DocumentsReadResult } from "@/lib/api/decode/capabilities/documents.read";
import {
  invalidWorkRequest,
  isCanonicalId,
  workGet,
} from "@/lib/api/work-route";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ documentId: string }> },
) {
  const { documentId } = await context.params;
  if (!isCanonicalId(documentId, "mdoc")) {
    return invalidWorkRequest("documentId is malformed");
  }
  return workGet(request, "document-read", "documents.read", {
    versionId: {
      gateway: "version_id", type: "string", pattern: /^mdver_[A-Za-z0-9]{8,64}$/,
    },
    includeBytes: { gateway: "include_bytes", type: "boolean" },
  }, { document_id: documentId }, {
    strictQuery: true,
    project: (result, payload) => {
      // The gateway has already strictly decoded the canonical safe view.
      const { version } = result as DocumentsReadResult;
      if (payload.include_bytes !== true && version.content_base64 !== null) {
        return null;
      }
      return { version: { ...version } };
    },
  });
}
