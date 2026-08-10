/**
 * Sign-in — synthetic identity provider only.
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
 * The real Entra/MSAL flow replaces this screen when a real app registration
 * exists (see `lib/auth/msal.config.ts`).
 */
import { admissibleSyntheticPrincipals } from "@/lib/auth/synthetic";
import { SignInForm } from "@/app/sign-in/sign-in-form";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SignInPage() {
  const offered = admissibleSyntheticPrincipals().map((p) => ({ key: p.key, label: p.label }));

  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
        <p className="mt-1 text-sm text-muted">MossAIc personal assistant</p>
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
