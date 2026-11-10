import { ReportCatalog } from "@/components/reports/report-catalog";

export const metadata = { title: "Reports — my-pa" };

/** Standalone reports: list and search (Reports Modernization WP07, contract U7). */
export default function ReportsPage() {
  return <ReportCatalog />;
}
