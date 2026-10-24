import { IssueView } from "@/components/issues/issue-view";

export const metadata = { title: "Issue — my-pa" };

/** One Issue: breadcrumb, header, timeline and lineage (record lineage S3 contract section 7.6). */
export default async function IssuePage({ params }: { params: Promise<{ issueId: string }> }) {
  const { issueId } = await params;
  return <IssueView issueId={issueId} />;
}
