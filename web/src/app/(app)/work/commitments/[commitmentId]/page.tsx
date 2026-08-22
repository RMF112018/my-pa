import { CommitmentDetailView } from "@/components/work/work-detail";
export const metadata = { title: "Commitment — my-pa" };
export default async function CommitmentPage({ params }: { params: Promise<{ commitmentId: string }> }) { const { commitmentId } = await params; return <CommitmentDetailView commitmentId={commitmentId} />; }
