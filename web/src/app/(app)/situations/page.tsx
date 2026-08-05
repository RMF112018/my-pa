import { NotConnected } from "@/components/ui/not-connected";

export const metadata = { title: "Situations — my-pa" };

export default function SituationsPage() {
  return (
    <section aria-labelledby="situations-heading" className="mx-auto max-w-2xl">
      <h1 id="situations-heading" className="mb-4 text-xl font-semibold text-moss-slate">
        Situations
      </h1>
      <NotConnected
        title="Situations"
        description="Situations gather what matters about a project, relationship, or topic into one purposeful view, with saved Frames and full provenance."
        arrivesWith="Arrives with WP-06 (R5 — relationship and project views). Nothing here is hidden; there is simply nothing connected yet."
      />
    </section>
  );
}
