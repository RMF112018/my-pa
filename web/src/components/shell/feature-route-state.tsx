import { SurfaceState } from "@/components/ui/surface-state";
import { PageHeader } from "@/components/shell/page-header";
export function FeatureRouteState({ title, description, state, detail }: { title: string; description: string; state: "unavailable" | "not_implemented" | "degraded"; detail: string }) { return <section className="mx-auto max-w-4xl"><PageHeader title={title} description={description} /><SurfaceState kind={state} title={state === "degraded" ? `${title} is partial` : `${title} is not available in this build`} detail={detail} /></section>; }
