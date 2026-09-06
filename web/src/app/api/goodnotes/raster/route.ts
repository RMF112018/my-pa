import type { NextRequest } from "next/server";
import { goodnotesRaster } from "@/lib/api/goodnotes-route";

export async function GET(request: NextRequest) {
  return goodnotesRaster(request);
}
