import { ReportCatalog } from "@/components/reports/report-catalog";

export const metadata = { title: "Trash — Reports — my-pa" };

/** Standalone reports in Trash, each restorable (Reports Modernization WP07, contract U7). */
export default function ReportsTrashPage() {
  return <ReportCatalog mode="trash" />;
}
