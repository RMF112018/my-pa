import type { NextRequest } from "next/server";
import { goodnotesCorrect } from "@/lib/api/goodnotes-route";

export async function POST(request: NextRequest) {
  return goodnotesCorrect(request);
}
