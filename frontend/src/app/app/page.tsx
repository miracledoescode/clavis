import { RuleBuilder } from "@/modules/rule-builder";

export default function AppHome() {
  return (
    <div className="mx-auto max-w-6xl p-6">
      <h1 className="font-serif text-2xl font-medium">Rule Builder</h1>
      <p className="mb-5 mt-1 text-sm text-muted-foreground">
        Describe your strategy in plain language. The Agent captures it as an editable spec that stays
        unmistakably yours, then saves and versions it.
      </p>
      <RuleBuilder />
    </div>
  );
}
