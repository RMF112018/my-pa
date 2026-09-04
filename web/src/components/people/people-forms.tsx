import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { peopleHome } from "@/lib/routes/people";

export function PeopleSearchForm({ query }: { query: string }) {
  return (
    <form
      method="get"
      action={peopleHome()}
      role="search"
      className="mb-4 flex flex-wrap items-end gap-3"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="people-q" className="text-sm font-medium text-moss-slate">
          Search people
        </label>
        <Input
          id="people-q"
          name="q"
          type="search"
          defaultValue={query}
          aria-describedby="people-q-hint"
        />
        <p id="people-q-hint" className="text-xs text-muted">
          A name match over your own entities. This is browse, not identity, and not a
          directory of everyone.
        </p>
      </div>
      <Button type="submit">Search</Button>
    </form>
  );
}

export function PeopleResolveForm({ reference }: { reference: string }) {
  return (
    <form method="get" action={peopleHome()} className="mb-6 flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="people-reference" className="text-sm font-medium text-moss-slate">
          Resolve a reference
        </label>
        <Input
          id="people-reference"
          name="reference"
          type="text"
          defaultValue={reference}
          aria-describedby="people-reference-hint"
        />
        <p id="people-reference-hint" className="text-xs text-muted">
          Asks who this names. An ambiguous answer stays ambiguous; nothing here merges.
        </p>
      </div>
      <Button type="submit" variant="secondary">
        Resolve
      </Button>
    </form>
  );
}
