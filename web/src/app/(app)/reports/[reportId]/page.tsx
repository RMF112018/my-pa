import { ReportView } from "@/components/reports/report-view";

export const metadata = { title: "Report — my-pa" };

/** One standalone report: versions, history and lifecycle (Reports Modernization WP07, contract U7). */
export default async function ReportPage({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <ReportView reportId={reportId} />;
}
