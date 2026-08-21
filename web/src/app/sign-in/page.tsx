/**
 * Sign-in — selected by the deployment's fail-closed identity mode.
 *
 * A **server** component, which it had to become: the set of principals this
 * deployment admits depends on `MYPA_GATEWAY_AUTH_MODE`, and that is server
 * configuration a client component cannot read and must not be shipped. It
 * resolves `admissibleSyntheticPrincipals()` and hands the interactive half only
 * the key and label of each — never the claims.
 *
 * Over a `local_operator` gateway that set has exactly one member (`D-15`), so
 * this screen offers one sign-in. The screen and `POST /api/session` cannot
 * disagree about it, because neither holds its own copy of the list.
 *
 * In local-operator mode the page accepts only the owner-held credential; the
 * Principal remains server-selected. In Entra mode it offers the dormant
 * server-side authorization-code flow.
 */
import { admissibleSyntheticPrincipals } from "@/lib/auth/synthetic";
import { authMode } from "@/lib/auth/mode";
import { SignInForm } from "@/app/sign-in/sign-in-form";
import { LocalOperatorSignInForm } from "@/app/sign-in/local-operator-sign-in-form";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Rendered per request, and this line is load-bearing rather than a default
 * anybody may tidy away.
 *
 * Without it Next prerenders this page at **build** time — `next build` reported
 * it as static — so the admissible set would be fixed by whatever
 * `MYPA_GATEWAY_AUTH_MODE` happened to be set to on the build machine. A build
 * run without it and then deployed against a `local_operator` gateway would ship
 * a page offering both principals, and the second button would be refused by
 * `POST /api/session` on every press. The refusal is what actually prevents the
 * cross-principal read, so nothing unsafe would be served either way; what would
 * break is the honesty of the screen, which is the half `D-15` added it for.
 */
export const dynamic = "force-dynamic";

export default function SignInPage() {
  const mode = authMode();
  if (mode === "entra") {
    return (
      <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
        </div>
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Sign in</CardTitle>
            <Badge>Microsoft Entra</Badge>
          </div>
          <CardBody>
            <p>Continue through the configured home tenant. Identity is derived from the validated callback.</p>
            <a className="mt-4 inline-flex rounded-md bg-moss-green px-4 py-2 text-on-interactive" href="/auth/sign-in">
              Continue with Microsoft Entra
            </a>
          </CardBody>
        </Card>
      </main>
    );
  }
  if (mode === "local_operator") {
    return (
      <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
        </div>
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Sign in</CardTitle>
            <Badge>Local operator</Badge>
          </div>
          <CardBody>
            <p>Authenticate as this deployment&apos;s single, server-selected operator.</p>
            <LocalOperatorSignInForm />
          </CardBody>
        </Card>
      </main>
    );
  }
  const offered = admissibleSyntheticPrincipals().map((p) => ({ key: p.key, label: p.label }));

  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
      </div>
      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Sign in</CardTitle>
          <Badge tone="synthetic">Synthetic provider</Badge>
        </div>
        <CardBody>
          <p>
            No live Entra registration is configured. Choose a synthetic development principal.
            Identity is derived from validated claims only — never from anything you type.
          </p>
          <SignInForm principals={offered} />
        </CardBody>
      </Card>
    </main>
  );
}
