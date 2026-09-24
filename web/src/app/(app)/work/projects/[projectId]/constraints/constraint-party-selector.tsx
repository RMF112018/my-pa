"use client";

/**
 * The canonical PartyRef selector shared by BIC and Responsible fields.
 *
 * `PC-CM-CAPTURE-AC-010`: a party is never guessed. There are exactly three
 * ways to add one, and each is explicit about which it is:
 *
 * - **Me** — the Principal party. Added once; a second "Add me" is disabled
 *   once it is already in the list, so there is no way to accumulate two
 *   Principal entries that would decode into the same identity twice.
 * - **Search** — `GET /api/people?q=` (`entities.search`), the same canonical
 *   entity search `people-page.tsx`/`resolve-panel.tsx` already use. Picking a
 *   result carries that entity's own `entity_id` forward as `entityId`; the
 *   display text shown here is never sent back as identity.
 * - **Not on file** — explicit unresolved wording, entered by the author and
 *   carrying no identity at all. This is the only path that can ever produce
 *   an `UNRESOLVED` party, and it requires a deliberate, separate action from
 *   search — nothing here silently downgrades an unmatched search term into
 *   an unresolved party.
 *
 * The value this component edits is already the request wire shape
 * (`RequestPartyRef`: `{kind, entityId?, label?}`, lower-case `kind`) so a
 * caller can hand it straight to `constraint-live.ts`'s mutation functions
 * without a second conversion step.
 */
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { RequestPartyRef } from "./constraint-live";

export type { RequestPartyRef } from "./constraint-live";

interface EntityHit {
  readonly entity_id: string;
  readonly display_name: string;
  readonly entity_type: string;
}

function partyKey(party: RequestPartyRef, index: number): string {
  return `${party.kind}:${party.entityId ?? party.label ?? "principal"}:${index}`;
}

/** The label this component shows for one party. Never used as identity. */
export function partyDisplayLabel(party: RequestPartyRef, principalLabel: string): string {
  if (party.kind === "principal") return principalLabel;
  if (party.kind === "entity") return party.label ?? party.entityId ?? "Entity";
  return party.label ?? "Unresolved";
}

export interface ConstraintPartySelectorProps {
  readonly label: string;
  readonly value: readonly RequestPartyRef[];
  readonly onChange: (next: readonly RequestPartyRef[]) => void;
  readonly principalLabel?: string;
  /** Stable prefix for every `data-testid` this instance renders. */
  readonly testIdPrefix: string;
  readonly disabled?: boolean;
}

export function ConstraintPartySelector({
  label,
  value,
  onChange,
  principalLabel = "Me",
  testIdPrefix,
  disabled = false,
}: ConstraintPartySelectorProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<readonly EntityHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);
  const [unresolvedText, setUnresolvedText] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    const term = query.trim();
    const id = ++requestId.current;
    if (term.length < 2) {
      void Promise.resolve().then(() => {
        if (id !== requestId.current) return;
        setResults([]);
        setSearchFailed(false);
        setSearching(false);
      });
      return;
    }
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (id === requestId.current) setSearching(true);
    });
    const timer = window.setTimeout(() => {
      void fetch(`/api/people?q=${encodeURIComponent(term)}`, {
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      })
        .then((response) => (response.ok ? (response.json() as Promise<{ entities?: readonly EntityHit[] }>) : Promise.reject(new Error("search failed"))))
        .then((body) => {
          if (id !== requestId.current) return;
          setResults(body.entities ?? []);
          setSearchFailed(false);
          setSearching(false);
        })
        .catch(() => {
          if (id !== requestId.current) return;
          setSearchFailed(true);
          setSearching(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  function add(party: RequestPartyRef) {
    onChange([...value, party]);
    setQuery("");
    setResults([]);
    setUnresolvedText("");
  }

  function remove(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  const hasPrincipal = value.some((party) => party.kind === "principal");

  return (
    <div className="grid gap-1 text-sm" data-testid={`${testIdPrefix}-selector`}>
      <span>{label}</span>
      <ul className="flex flex-wrap gap-1" data-testid={`${testIdPrefix}-chips`}>
        {value.map((party, index) => (
          <li key={partyKey(party, index)}>
            <Badge tone="neutral">
              {partyDisplayLabel(party, principalLabel)}
              {!disabled ? (
                <button
                  type="button"
                  className="ml-1"
                  aria-label={`Remove ${partyDisplayLabel(party, principalLabel)}`}
                  data-testid={`${testIdPrefix}-remove-${index}`}
                  onClick={() => remove(index)}
                >
                  ×
                </button>
              ) : null}
            </Badge>
          </li>
        ))}
        {value.length === 0 ? <li className="text-muted">Not recorded</li> : null}
      </ul>
      {!disabled ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button type="button" size="sm" variant="secondary" data-testid={`${testIdPrefix}-add`}>
              Add {label}
            </Button>
          </PopoverTrigger>
          <PopoverContent aria-label={`Add ${label}`} className="grid w-72 gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={hasPrincipal}
              data-testid={`${testIdPrefix}-add-me`}
              onClick={() => add({ kind: "principal" })}
            >
              Add me
            </Button>
            <label className="grid gap-1">
              Search people or organizations
              <Input
                type="search"
                value={query}
                placeholder="Type at least 2 characters…"
                data-testid={`${testIdPrefix}-search`}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            {searching ? (
              <p role="status" className="text-xs text-muted">
                Searching…
              </p>
            ) : null}
            {searchFailed ? (
              <p role="alert" className="text-xs text-moss-coral-strong">
                The search could not be read.
              </p>
            ) : null}
            {results.length > 0 ? (
              <ul className="grid gap-1" data-testid={`${testIdPrefix}-results`}>
                {results.map((hit) => (
                  <li key={hit.entity_id}>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      data-testid={`${testIdPrefix}-result-${hit.entity_id}`}
                      onClick={() => add({ kind: "entity", entityId: hit.entity_id, label: hit.display_name })}
                    >
                      {hit.display_name}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
            <label className="grid gap-1">
              Not on file — enter wording
              <Input
                type="text"
                value={unresolvedText}
                data-testid={`${testIdPrefix}-unresolved-text`}
                onChange={(event) => setUnresolvedText(event.target.value)}
              />
            </label>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={unresolvedText.trim().length === 0}
              data-testid={`${testIdPrefix}-add-unresolved`}
              onClick={() => add({ kind: "unresolved", label: unresolvedText.trim() })}
            >
              Add as unresolved
            </Button>
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}
