import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { GrantEnrollment } from "@/components/auth/grant-enrollment";

export const dynamic = "force-dynamic";

export default function OperatorRecoveryPage() {
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
      </div>
      <Card>
        <CardTitle>Operator recovery</CardTitle>
        <CardBody>
          <p>
            Paste the operator recovery grant, then register a replacement passkey. The previous
            session is replaced if this succeeds.
          </p>
          <GrantEnrollment
            kind="operator-recovery"
            grantLabel="Operator recovery grant"
            submitLabel="Register a replacement passkey"
          />
        </CardBody>
      </Card>
    </main>
  );
}
