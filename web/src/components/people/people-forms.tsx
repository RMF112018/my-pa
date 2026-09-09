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
        <label htmlFor="people-q" className="text-sm font-medium text-text-primary">
          Find a person
        </label>
        <Input
          id="people-q"
          name="q"
          type="search"
          defaultValue={query}
          aria-describedby="people-q-hint"
        />
        <p id="people-q-hint" className="text-xs text-muted">
          Search by name among people already in your records.
        </p>
      </div>
      <Button type="submit">Search</Button>
    </form>
  );
}

export function PeopleResolveForm({ reference }: { reference: string }) {
  return (
    <form method="get" action={peopleHome()} className="mt-3 flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="people-reference" className="text-sm font-medium text-text-primary">
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
          Asks who this names.
        </p>
      </div>
      <Button type="submit" variant="secondary">
        Resolve
      </Button>
    </form>
  );
}

/** Search is the default. Resolve stays behind a disclosure unless a deep link already has `reference`. */
export function PeopleLookupForms({
  query,
  reference,
}: {
  query: string;
  reference: string;
}) {
  return (
    <>
      <PeopleSearchForm query={query} />
      <details
        className="mb-6"
        data-testid="people-resolve-advanced"
        {...(reference ? { open: true } : {})}
      >
        <summary className="cursor-pointer text-sm font-medium text-text-primary">
          Resolve a reference
          <span className="ml-2 font-normal text-muted">Advanced</span>
        </summary>
        <PeopleResolveForm reference={reference} />
      </details>
    </>
  );
}
