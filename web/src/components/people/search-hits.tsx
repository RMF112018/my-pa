import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { peopleEntity } from "@/lib/routes/people";
import type { EntitySummary } from "@/lib/api/decode/capabilities/entities.search";
import { codeLabel } from "./format";

export function SearchHits({ entities }: { entities: readonly EntitySummary[] }) {
  return (
    <ul data-testid="people-search-hits" className="space-y-3">
      {entities.map((row) => (
        <li key={row.entity_id}>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <CardTitle>
                <Link
                  href={peopleEntity(row.entity_id)}
                  className="text-moss-slate underline decoration-moss-green/40 underline-offset-2"
                >
                  {row.display_name}
                </Link>
              </CardTitle>
              <Badge tone={row.status === "active" ? "green" : "gold"}>{codeLabel(row.status)}</Badge>
            </div>
            <CardBody>
              <p className="font-mono text-xs break-all text-muted">{row.entity_id}</p>
              <p className="mt-1 text-sm">{codeLabel(row.entity_type)}</p>
              {row.affiliated_organizations.length > 0 ? (
                <p className="mt-1 text-sm text-muted">{row.affiliated_organizations.join(", ")}</p>
              ) : null}
              {row.project_roles.length > 0 ? (
                <p className="text-sm text-muted">{row.project_roles.join(", ")}</p>
              ) : null}
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
  );
}
