import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import { syntheticReviewCases } from "@/lib/fixtures/review";
import { ReviewWorkbench } from "@/components/review/review-workbench";

export const metadata = { title: "Review — my-pa" };

export default async function ReviewPage() {
  const cookieStore = await cookies();
  const principal = await verifySession(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const cases = syntheticReviewCases(principal);

  return (
    <section aria-labelledby="review-heading" className="mx-auto max-w-2xl">
      <h1 id="review-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Review
      </h1>
      <p className="mb-4 text-sm text-muted">
        Proposals wait here for your disposition. Nothing is asserted on your behalf — a captured
        item becomes a canonical record only when you accept or correct-and-accept it. Every case
        below is a principal-scoped synthetic fixture; no live sources are connected yet.
      </p>
      <ReviewWorkbench cases={cases} />
    </section>
  );
}
