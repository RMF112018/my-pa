import { NotConnected } from "@/components/ui/not-connected";

export const metadata = { title: "Library — my-pa" };

export default function LibraryPage() {
  return (
    <section aria-labelledby="library-heading" className="mx-auto max-w-2xl">
      <h1 id="library-heading" className="mb-4 text-xl font-semibold text-moss-slate">
        Library
      </h1>
      <NotConnected
        title="Library"
        description="Library is the browsable record of your sources, assertions, and receipts — everything my-pa knows, inspectable and traceable."
        arrivesWith="Arrives with WP-03 onward as sources and receipts accumulate. No sources are connected yet."
      />
    </section>
  );
}
