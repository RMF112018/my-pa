import { IssueList } from "@/components/issues/issue-list";

export const metadata = { title: "Issues — my-pa" };

/** The Issues index (record lineage S3 contract section 7.6). */
export default function IssuesPage() {
  return <IssueList />;
}
