import { AuthGate } from "@/components/auth-gate";

import { AppNav } from "./_nav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="border-b border-border">
        <AppNav />
      </div>
      {children}
    </AuthGate>
  );
}
