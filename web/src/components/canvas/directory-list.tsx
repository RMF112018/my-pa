import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { peopleEntity } from "@/lib/routes/people";
import { codeLabel } from "@/components/people/format";
import type { GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

export function DirectoryList({ nodes }: { nodes: readonly GraphNode[] }) {
  return (
    <ul data-testid="canvas-directory" className="space-y-3">
      {nodes.map((node) => (
        <li key={node.entity_id}>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <CardTitle>
                <Link
                  href={peopleEntity(node.entity_id)}
                  className="text-moss-slate underline decoration-moss-green/40 underline-offset-2"
                >
                  {node.display_label}
                </Link>
              </CardTitle>
              <Badge tone={node.status === "active" ? "green" : "gold"}>{codeLabel(node.status)}</Badge>
            </div>
            <CardBody>
              <p className="text-sm">{codeLabel(node.entity_type)}</p>
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
  );
}
