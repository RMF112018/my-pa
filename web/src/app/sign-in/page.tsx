/**
 * Sign-in — selected by the deployment's fail-closed identity mode.
 *
 * A **server** component: the set of principals this deployment admits depends
 * on `MYPA_GATEWAY_AUTH_MODE`, and that is server configuration a client
 * component cannot read and must not be shipped. It resolves
 * `admissibleSyntheticPrincipals()` and hands the interactive half only the
 * key and label of each — never the claims.
 *
 * `passkey` is the production web mode and offers only PasskeySignIn.
 * `synthetic` offers the development principal buttons plus passkey.
 */
import { admissibleSyntheticPrincipals } from "@/lib/auth/synthetic";
import { authMode } from "@/lib/auth/mode";
import { SignInForm } from "@/app/sign-in/sign-in-form";
import { PasskeySignIn } from "@/app/sign-in/passkey-sign-in";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Rendered per request, and this line is load-bearing rather than a default
 * anybody may tidy away.
 *
 * Without it Next prerenders this page at **build** time — `next build` reported
 * it as static — so the admissible set would be fixed by whatever
 * `MYPA_GATEWAY_AUTH_MODE` happened to be set to on the build machine.
 */
export const dynamic = "force-dynamic";

export default function SignInPage() {
  const mode = authMode();

  if (mode === "passkey") {
    return (
      <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
        </div>
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Sign in</CardTitle>
            <Badge>Passkey</Badge>
          </div>
          <CardBody>
            <p>Sign in with a passkey or a recovery code.</p>
            <PasskeySignIn />
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
            No live passkey enrolment is required in this development mode. Choose a
            synthetic principal, or sign in with a passkey when one is registered.
            Identity is derived from validated claims only — never from anything you type.
          </p>
          <SignInForm principals={offered} />
          <PasskeySignIn />
        </CardBody>
      </Card>
    </main>
  );
}
