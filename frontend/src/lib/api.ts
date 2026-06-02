import type { StrategySpec } from "@/contract/types";

// Base URL of the FastAPI engine. The browser talks only to FastAPI and Supabase.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Persist a strategy. Scaffold stub — typed against the Strategy JSON contract so
 * the canvas -> StrategySpec -> engine path is wired end to end. The real
 * implementation (auth headers, error handling) lands with the Strategy Engine.
 */
export async function saveStrategy(spec: StrategySpec): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/strategies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
}
