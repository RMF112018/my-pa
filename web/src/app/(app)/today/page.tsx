import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import { syntheticPulse } from "@/lib/fixtures/pulse";
import { PulseList } from "@/components/pulse/pulse-list";

export const metadata = { title: "Today — my-pa" };

export default async function TodayPage() {
  const cookieStore = await cookies();
  const principal = await verifySession(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const items = syntheticPulse(principal);

  return (
    <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
      <h1 id="today-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Today
      </h1>
      <p className="mb-4 text-sm text-muted">
        Pulse — what needs your attention, each with a reason and a next step. All items below
        are synthetic fixtures; no live sources are connected yet.
      </p>
      <PulseList items={items} />
    </section>
  );
}
