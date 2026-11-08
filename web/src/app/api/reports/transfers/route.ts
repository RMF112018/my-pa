import type { NextRequest } from "next/server";
import { reportsMutation, TRANSFER_BEGIN_FIELDS } from "@/lib/api/reports-route";

/**
 * `POST /api/reports/transfers` -> `reports.transfer.begin`. The browser
 * stages identity bytes only: `encoding` is fixed here, never read from the body.
 */
export async function POST(request: NextRequest) {
  return reportsMutation(request, "reports.transfer.begin", TRANSFER_BEGIN_FIELDS, {
    encoding: "identity",
  });
}
