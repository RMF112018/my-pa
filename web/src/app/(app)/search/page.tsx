import { SearchPage } from "@/app/(app)/search/search-page";

export const metadata = { title: "Search — my-pa" };
export const dynamic = "force-dynamic";

function oneParam(
  params: Record<string, string | string[] | undefined>,
  name: string,
): string {
  const raw = params[name];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const enrollmentId = oneParam(params, "enrollmentId");
  return (
    <SearchPage initialQuery={oneParam(params, "q")} enrollmentId={enrollmentId || undefined} />
  );
}
