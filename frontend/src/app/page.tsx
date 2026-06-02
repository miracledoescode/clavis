import { AuthGate } from "@/components/auth-gate";
import { RuleBuilder } from "@/modules/rule-builder";

export default function Home() {
  return (
    <main className="min-h-screen">
      <AuthGate>
        <div className="mx-auto max-w-6xl p-6">
          <h1 className="text-xl font-semibold">Clavis · Rule Builder</h1>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            Describe your strategy in plain language. The Agent captures it as an editable canvas that
            stays unmistakably yours, then saves and versions it.
          </p>
          <RuleBuilder />
        </div>
      </AuthGate>
    </main>
  );
}
