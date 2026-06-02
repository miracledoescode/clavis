"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";

/**
 * Thin Supabase Auth spine: email + password, session persisted by supabase-js.
 * Renders the sign-in form until there is a session, then the app.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (loading) return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
  if (!session) return <SignInForm />;

  return (
    <div>
      <div className="flex items-center justify-between border-b px-6 py-3 text-sm">
        <span className="text-muted-foreground">Signed in as {session.user.email}</span>
        <button
          type="button"
          onClick={() => supabase.auth.signOut()}
          className="rounded border px-3 py-1 hover:bg-accent"
        >
          Sign out
        </button>
      </div>
      {children}
    </div>
  );
}

function SignInForm() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    const { error: authError } =
      mode === "signin"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password });
    if (authError) setError(authError.message);
    else if (mode === "signup") setInfo("Account created. If email confirmation is on, confirm then sign in.");
    setBusy(false);
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border p-6">
      <h1 className="mb-1 text-lg font-semibold">Clavis</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        Sign in to design, build, and deploy your trading Agents.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="email"
          required
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded border bg-background px-3 py-2 text-sm"
        />
        <input
          type="password"
          required
          minLength={6}
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded border bg-background px-3 py-2 text-sm"
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
        {info && <p className="text-sm text-muted-foreground">{info}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>
      </form>
      <button
        type="button"
        onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
        className="mt-3 text-sm text-muted-foreground underline"
      >
        {mode === "signin" ? "Need an account? Sign up" : "Have an account? Sign in"}
      </button>
    </div>
  );
}
