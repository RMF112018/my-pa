import Link from "next/link";
import { Card, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EpistemicLabel } from "@/components/ui/epistemic-label";
import { DegradedBanner } from "@/components/ui/surface-state";
import { peopleEntity } from "@/lib/routes/people";
import type { EntityProfileView } from "@/lib/api/decode/capabilities/entities.profile";
import type {
  AffiliationView,
  EntityAddressView,
  CommunicationMethodView,
  EntityNameView,
  ParticipationView,
} from "@/lib/api/decode/capabilities/_entity-read-helpers";
import { lifecycleIsCurrent, participationIsCurrent, partitionByCurrency } from "./currency";
import { codeLabel, effectiveWindow, moment } from "./format";

const STATUS_TONE: Record<EntityProfileView["entity"]["status"], "green" | "gold" | "coral" | "neutral"> = {
  active: "green",
  inactive: "gold",
  historical: "gold",
  merged_redirect: "coral",
  archived: "neutral",
};

function Names({ names }: { names: readonly EntityNameView[] }) {
  if (names.length === 0) {
    return <p className="text-sm text-muted">No typed names on file.</p>;
  }
  return (
    <ul>
      {names.map((name) => (
        <li key={name.entity_name_id} className="text-sm">
          <span className="font-medium">{name.display_value}</span>
          <span className="ml-2 text-xs text-muted">
            {codeLabel(name.name_type_code)}
            {name.is_preferred ? " · preferred" : ""}
            {name.state !== "active" ? ` · ${codeLabel(name.state)}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Addresses({
  addresses,
  withheld,
}: {
  addresses: readonly EntityAddressView[];
  withheld: boolean;
}) {
  if (withheld && addresses.length === 0) {
    return <p className="text-sm text-muted">Addresses were withheld from this profile.</p>;
  }
  if (addresses.length === 0) {
    return <p className="text-sm text-muted">No addresses on file.</p>;
  }
  return (
    <ul className="space-y-2">
      {addresses.map((address) => {
        const lines = [address.line1, address.line2, address.city, address.region, address.postal_code, address.country]
          .filter((part): part is string => Boolean(part));
        return (
          <li key={address.entity_address_id} className="text-sm">
            <p>{lines.length > 0 ? lines.join(", ") : address.label ?? "Address on file"}</p>
            <p className="text-xs text-muted">
              {codeLabel(address.address_type_code)}
              {address.is_preferred ? " · preferred" : ""}
              {address.state !== "active" ? ` · ${codeLabel(address.state)}` : ""}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function CommunicationMethods({
  methods,
  withheld,
}: {
  methods: readonly CommunicationMethodView[];
  withheld: boolean;
}) {
  if (withheld && methods.length === 0) {
    return <p className="text-sm text-muted">Communication methods were withheld from this profile.</p>;
  }
  if (methods.length === 0) {
    return <p className="text-sm text-muted">No communication methods on file.</p>;
  }
  return (
    <ul className="space-y-2">
      {methods.map((method) => (
        <li key={method.communication_method_id} className="text-sm">
          <p>{method.display_value}</p>
          <p className="text-xs text-muted">
            {codeLabel(method.method_type_code)} · {codeLabel(method.usage_context_code)} ·{" "}
            {codeLabel(method.verification_status_code)}
            {method.is_preferred ? " · preferred" : ""}
            {method.state !== "active" ? ` · ${codeLabel(method.state)}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

function ParticipationGroup({
  title,
  testId,
  rows,
  asProject,
}: {
  title: string;
  testId: string;
  rows: readonly ParticipationView[];
  asProject: boolean;
}) {
  if (rows.length === 0) return null;
  const { current, historical } = partitionByCurrency(rows, participationIsCurrent);
  return (
    <section className="mt-6" aria-labelledby={testId} data-testid={testId}>
      <h3 id={testId} className="text-sm font-medium text-moss-slate">
        {title}
      </h3>
      {current.length > 0 ? (
        <div className="mt-2" data-testid={`${testId}-current`}>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Current</h4>
          <ul className="mt-1 space-y-1">
            {current.map((row) => (
              <ParticipationItem key={row.participation_id} row={row} asProject={asProject} />
            ))}
          </ul>
        </div>
      ) : null}
      {historical.length > 0 ? (
        <div className="mt-2" data-testid={`${testId}-historical`}>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Historical</h4>
          <ul className="mt-1 space-y-1">
            {historical.map((row) => (
              <ParticipationItem key={row.participation_id} row={row} asProject={asProject} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function ParticipationItem({ row, asProject }: { row: ParticipationView; asProject: boolean }) {
  const counterpartId = asProject ? row.participant_entity_id : row.project_entity_id;
  const label = asProject
    ? row.role_text ?? row.role_code ?? "Participant"
    : row.project_display_name ?? row.role_text ?? "Project";
  return (
    <li className="text-sm">
      <Link href={peopleEntity(counterpartId)} className="underline decoration-moss-green/40">
        {label}
      </Link>
      <span className="ml-2 text-xs text-muted">
        {codeLabel(row.relationship_status_code)} · {codeLabel(row.state)}
      </span>
    </li>
  );
}

function AffiliationGroup({
  title,
  testId,
  rows,
}: {
  title: string;
  testId: string;
  rows: readonly AffiliationView[];
}) {
  if (rows.length === 0) return null;
  const { current, historical } = partitionByCurrency(rows, lifecycleIsCurrent);
  return (
    <section className="mt-6" aria-labelledby={testId} data-testid={testId}>
      <h3 id={testId} className="text-sm font-medium text-moss-slate">
        {title}
      </h3>
      {current.length > 0 ? (
        <div className="mt-2" data-testid={`${testId}-current`}>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Current</h4>
          <ul className="mt-1 space-y-1">
            {current.map((row) => (
              <AffiliationItem key={row.affiliation_id} row={row} />
            ))}
          </ul>
        </div>
      ) : null}
      {historical.length > 0 ? (
        <div className="mt-2" data-testid={`${testId}-historical`}>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Historical</h4>
          <ul className="mt-1 space-y-1">
            {historical.map((row) => (
              <AffiliationItem key={row.affiliation_id} row={row} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function AffiliationItem({ row }: { row: AffiliationView }) {
  const org = row.organization_entity_id;
  return (
    <li className="text-sm">
      {org ? (
        <Link href={peopleEntity(org)} className="underline decoration-moss-green/40">
          {row.job_title ?? codeLabel(row.affiliation_type_code)}
        </Link>
      ) : (
        <span>{row.job_title ?? codeLabel(row.affiliation_type_code)}</span>
      )}
      <span className="ml-2 text-xs text-muted">
        {codeLabel(row.affiliation_type_code)} · {codeLabel(row.state)}
      </span>
    </li>
  );
}

export function EntityProfilePanel({
  profile,
  headingLevel = 2,
  headingId,
}: {
  profile: EntityProfileView;
  headingLevel?: 1 | 2;
  headingId?: string;
}) {
  const { entity } = profile;
  const Heading = headingLevel === 1 ? "h1" : "h2";
  const addressWithheld = profile.limitations.includes("more_addresses_than_this_profile_carries");
  const commsWithheld = profile.limitations.includes(
    "more_communication_methods_than_this_profile_carries",
  );

  return (
    <article data-testid="people-profile" className="space-y-4">
      {entity.status === "merged_redirect" ? (
        <div
          role="alert"
          data-testid="people-merged-redirect"
          className="rounded-md border border-moss-coral/40 border-l-4 border-l-moss-coral-strong bg-moss-coral/10 p-3 text-sm"
        >
          <p className="font-medium text-moss-slate">This entity was merged away.</p>
          <p className="mt-1 text-muted">
            The page does not guess a survivor. A link appears only when the record names one.
          </p>
          {entity.superseded_by_entity_id ? (
            <p className="mt-2">
              <Link
                href={peopleEntity(entity.superseded_by_entity_id)}
                className="font-medium text-moss-green underline"
                data-testid="people-survivor-link"
              >
                Open surviving entity
              </Link>
              <span className="ml-2 font-mono text-xs break-all text-muted">
                {entity.superseded_by_entity_id}
              </span>
            </p>
          ) : (
            <p className="mt-2 text-muted" data-testid="people-survivor-missing">
              No surviving entity identifier was supplied, so nothing was inferred.
            </p>
          )}
        </div>
      ) : null}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <Heading
            id={headingId}
            className={`${headingLevel === 1 ? "text-2xl tracking-tight" : "text-lg"} font-semibold text-moss-slate`}
          >
            {entity.display_name}
          </Heading>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[entity.status]}>{codeLabel(entity.status)}</Badge>
            {profile.is_complete ? (
              <EpistemicLabel role="canonical" />
            ) : (
              <EpistemicLabel role="pipeline-incomplete" />
            )}
          </div>
        </div>
        <CardBody>
          <dl className="grid grid-cols-[minmax(6rem,9rem)_1fr] gap-x-2 gap-y-1">
            <dt className="text-muted">Type</dt>
            <dd>{codeLabel(entity.entity_type)}</dd>
            <dt className="text-muted">Stable ID</dt>
            <dd className="font-mono text-xs break-all" data-testid="people-entity-id">
              {entity.entity_id}
            </dd>
            <dt className="text-muted">Canonical name</dt>
            <dd>{entity.canonical_name}</dd>
          </dl>
        </CardBody>
      </Card>

      {profile.limitations.length > 0 || !profile.is_complete ? (
        <DegradedBanner scope="this profile" limitations={profile.limitations} />
      ) : null}

      {profile.organization_profile ? (
        <section aria-labelledby="people-org-heading">
          <h3 id="people-org-heading" className="text-sm font-medium text-moss-slate">
            Organization
          </h3>
          <p className="mt-1 text-sm">
            {codeLabel(profile.organization_profile.organization_kind_code)} · legal identity{" "}
            {codeLabel(profile.organization_profile.legal_identity_status_code)}
          </p>
        </section>
      ) : null}

      <section aria-labelledby="people-profile-names">
        <h3 id="people-profile-names" className="text-sm font-medium text-moss-slate">
          Names
        </h3>
        <Names names={profile.names} />
      </section>

      <section aria-labelledby="people-profile-addresses">
        <h3 id="people-profile-addresses" className="text-sm font-medium text-moss-slate">
          Addresses
        </h3>
        <Addresses addresses={profile.addresses} withheld={addressWithheld} />
      </section>

      <section aria-labelledby="people-profile-communication">
        <h3 id="people-profile-communication" className="text-sm font-medium text-moss-slate">
          Communication
        </h3>
        <CommunicationMethods methods={profile.communication_methods} withheld={commsWithheld} />
      </section>

      <ParticipationGroup
        title="Participations as participant"
        testId="people-participations-participant"
        rows={profile.participations_as_participant}
        asProject={false}
      />
      <ParticipationGroup
        title="Participations as project"
        testId="people-participations-project"
        rows={profile.participations_as_project}
        asProject
      />
      <AffiliationGroup
        title="Affiliations as person"
        testId="people-affiliations-person"
        rows={profile.affiliations_as_person}
      />
      <AffiliationGroup
        title="Affiliations as organization"
        testId="people-affiliations-organization"
        rows={profile.affiliations_as_organization}
      />

      <section aria-labelledby="people-profile-provenance" className="text-sm">
        <h3 id="people-profile-provenance" className="font-medium text-moss-slate">
          Provenance
        </h3>
        <p className="mt-1 text-muted">
          Assembled {moment(profile.assembled_at)}
          {profile.is_complete ? "" : " · this card is not complete"}
        </p>
        {effectiveWindow(entity.created_at, entity.updated_at) ? (
          <p className="mt-1 text-xs text-muted">
            Created {moment(entity.created_at)} · updated {moment(entity.updated_at)}
          </p>
        ) : null}
      </section>
    </article>
  );
}
