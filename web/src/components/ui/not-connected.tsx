import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Honest scaffold state — names what this destination will do and states
 * plainly that it is not yet connected. Never fakes data.
 */
export function NotConnected({
  title,
  description,
  arrivesWith,
}: {
  title: string;
  description: string;
  arrivesWith: string;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>{title}</CardTitle>
        <Badge tone="gold">Not yet connected</Badge>
      </div>
      <CardBody>
        <p>{description}</p>
        <p className="mt-2 text-xs">{arrivesWith}</p>
      </CardBody>
    </Card>
  );
}
