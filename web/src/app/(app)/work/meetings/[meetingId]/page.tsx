import { MeetingView } from "./meeting-view";

export const metadata = { title: "Meeting — my-pa" };

/** The minimal Meeting view (record lineage S3 contract section 7.6, D-18). */
export default async function MeetingPage({ params }: { params: Promise<{ meetingId: string }> }) {
  const { meetingId } = await params;
  return <MeetingView meetingId={meetingId} />;
}
