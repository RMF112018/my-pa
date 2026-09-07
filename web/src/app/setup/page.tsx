import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { GrantEnrollment } from "@/components/auth/grant-enrollment";

export const dynamic = "force-dynamic";

export default function SetupPage() {
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
      </div>
      <Card>
        <CardTitle>Owner setup</CardTitle>
        <CardBody>
          <p>Paste the one-time setup grant, then create the first passkey for this deployment.</p>
          <GrantEnrollment
            kind="bootstrap"
            grantLabel="Setup grant"
            submitLabel="Create the owner passkey"
          />
        </CardBody>
      </Card>
    </main>
  );
}
