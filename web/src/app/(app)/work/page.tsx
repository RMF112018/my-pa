import { Workbench } from "@/components/work/workbench";
import { parseWorkUrlState } from "@/lib/api/work-url";
export const metadata = { title: "Work — my-pa" };
export default async function WorkPage({ searchParams }: { searchParams: Promise<Record<string, string | readonly string[] | undefined>> }) {
  return <Workbench initialState={parseWorkUrlState(await searchParams)} />;
}
