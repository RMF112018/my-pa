import { ReportEditForm } from "@/components/reports/report-edit-form";

export const metadata = { title: "Edit report — my-pa" };

/** Edit one active standalone report (Reports Modernization WP07, contract U5-U7). */
export default async function EditReportPage({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <ReportEditForm reportId={reportId} />;
}
