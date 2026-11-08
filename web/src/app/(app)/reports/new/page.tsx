import { ReportNewForm } from "@/components/reports/report-new-form";

export const metadata = { title: "New report — my-pa" };

/** Publish one standalone report (Reports Modernization WP07, contract U6/U7). */
export default function NewReportPage() {
  return <ReportNewForm />;
}
