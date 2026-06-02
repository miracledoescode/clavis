import type { StrategySpec } from "@/contract/types";
import type { ParseResult } from "@/modules/rule-builder/types";
import { supabase } from "@/lib/supabase";

// Base URL of the FastAPI engine. The browser talks only to FastAPI and Supabase.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Attach the signed-in user's Supabase access token; the engine verifies it. */
async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("You are not signed in.");
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

/** A persisted strategy row (subset returned by the engine). */
export interface StrategyRow {
  id: string;
  name: string;
  version: number;
  status?: string;
  updated_at?: string;
}

/** Natural language -> block | clarification | incomplete | spec. */
export async function parseStrategy(text: string): Promise<ParseResult> {
  const res = await fetch(`${API_BASE_URL}/strategies/parse`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Parse request failed (${res.status})`);
  return (await res.json()) as ParseResult;
}

/** Validate + persist a new strategy (version 1). */
export async function createStrategy(name: string, spec: StrategySpec): Promise<StrategyRow> {
  const res = await fetch(`${API_BASE_URL}/strategies`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ name, spec }),
  });
  if (!res.ok) throw new Error(`Save failed (${res.status})`);
  return (await res.json()) as StrategyRow;
}

/** Validate + persist an edit (bumps the version, writes a new snapshot). */
export async function updateStrategy(
  id: string,
  name: string | null,
  spec: StrategySpec,
): Promise<StrategyRow> {
  const res = await fetch(`${API_BASE_URL}/strategies/${id}`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify({ name, spec }),
  });
  if (!res.ok) throw new Error(`Update failed (${res.status})`);
  return (await res.json()) as StrategyRow;
}

export async function listStrategies(): Promise<StrategyRow[]> {
  const res = await fetch(`${API_BASE_URL}/strategies`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`List failed (${res.status})`);
  return (await res.json()) as StrategyRow[];
}
