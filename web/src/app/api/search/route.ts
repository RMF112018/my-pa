import { type NextRequest } from "next/server";
import { searchGet } from "@/lib/api/search-route";

export async function GET(request: NextRequest) {
  return searchGet(request);
}
