import { NotConnected } from "@/components/ui/not-connected";

export const metadata = { title: "Review — my-pa" };

export default function ReviewPage() {
  return (
    <section aria-labelledby="review-heading" className="mx-auto max-w-2xl">
      <h1 id="review-heading" className="mb-4 text-xl font-semibold text-moss-slate">
        Review
      </h1>
      <NotConnected
        title="Review"
        description="Review is where proposals wait for your disposition. Nothing is asserted on your behalf — captured items become proposals, and you accept, amend, or reject them."
        arrivesWith="Arrives with WP-05 (R4 — review workbench). Captures made now will surface here once the pipeline lands (WP-03)."
      />
    </section>
  );
}
