import type { AgentProposal, AgentDecisionLog, RejectReasonChip, StrategySpec } from "@/contract/types";
import type { BacktestRow } from "@/modules/backtest-lab/types";
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
  /** Live deployment state: "stopped" (default) | "deployed". */
  deployment_status?: DeploymentStatus;
  updated_at?: string;
}

export type DeploymentStatus = "stopped" | "deployed";

/** Deploy Hub status: durable deployment_status + optional in-process loop state. */
export interface DeployStatus {
  id: string;
  deployment_status: DeploymentStatus;
  /** Present only when a live runner is attached (null in local dev / CI). */
  loop_state?: string | null;
}

/** Natural language -> block | clarification | incomplete | spec. */
export async function parseStrategy(text: string): Promise<ParseResult> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies/parse`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Parse request failed (${res.status})`);
  return (await res.json()) as ParseResult;
}

/** Validate + persist a new strategy (version 1). */
export async function createStrategy(name: string, spec: StrategySpec): Promise<StrategyRow> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies`, {
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
  const res = await fetch(`${API_BASE_URL}/v1/strategies/${id}`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify({ name, spec }),
  });
  if (!res.ok) throw new Error(`Update failed (${res.status})`);
  return (await res.json()) as StrategyRow;
}

export async function listStrategies(): Promise<StrategyRow[]> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`List failed (${res.status})`);
  return (await res.json()) as StrategyRow[];
}

/** Queue a backtest of a saved strategy. Returns the new backtest id + status. */
export async function runBacktest(
  strategyId: string,
  params?: Record<string, unknown>,
): Promise<{ id: string; status: string }> {
  const res = await fetch(`${API_BASE_URL}/v1/backtests`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ strategy_id: strategyId, params: params ?? null }),
  });
  if (!res.ok) throw new Error(`Backtest request failed (${res.status})`);
  return (await res.json()) as { id: string; status: string };
}

/** Poll a backtest by id (status -> done with the report, or error). */
export async function getBacktest(id: string): Promise<BacktestRow> {
  const res = await fetch(`${API_BASE_URL}/v1/backtests/${id}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`Backtest fetch failed (${res.status})`);
  return (await res.json()) as BacktestRow;
}

// --------------------------------------------------------------------------- //
// Deploy Hub — deploy / kill-switch / status                                  //
// The engine validates the spec and enforces the tier's live-Agent limit;     //
// SL/TP stay broker-managed, so Stop never closes open positions.             //
// --------------------------------------------------------------------------- //

/** Deploy a saved strategy's live Agent (validate -> tier check -> go live). */
export async function deployStrategy(strategyId: string): Promise<DeployStatus> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies/${strategyId}/deploy`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(await deployErrorMessage(res, "Deploy failed"));
  }
  return (await res.json()) as DeployStatus;
}

/** Kill switch: stop the live Agent. Open positions stay broker-managed (SL/TP). */
export async function stopStrategy(strategyId: string): Promise<DeployStatus> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies/${strategyId}/stop`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Stop failed"));
  return (await res.json()) as DeployStatus;
}

/** Current deployment_status (+ in-process loop state when a runner is attached). */
export async function getDeployStatus(strategyId: string): Promise<DeployStatus> {
  const res = await fetch(`${API_BASE_URL}/v1/strategies/${strategyId}/status`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Status fetch failed"));
  return (await res.json()) as DeployStatus;
}

/** Surface the engine's `detail` (e.g. tier-limit 403) instead of a bare code. */
async function deployErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    if (body?.detail) return body.detail;
  } catch {
    // non-JSON body; fall through to the generic message
  }
  return `${fallback} (${res.status})`;
}

// --------------------------------------------------------------------------- //
// Co-Pilot — approve/reject the live loop's proposals + the decision history  //
// (the RLHF capture surface CLAUDE.md calls "the moat"). Approve/reject route //
// through the SAME AgentLoop.on_approval/on_rejection path Telegram uses — no //
// separate execution logic.                                                  //
// --------------------------------------------------------------------------- //

/** A pending proposal awaiting the trader's decision. */
export interface PendingProposal {
  proposal_id: string;
  strategy_id: string;
  proposal: AgentProposal;
  user_decision: "pending";
  confidence_score: number;
  logged_at: string;
}

/** A decided proposal (approve / reject / invalidated / executed). */
export interface DecisionLogRow extends AgentDecisionLog {
  proposal_id: string;
  strategy_id: string;
}

export async function listPendingProposals(): Promise<PendingProposal[]> {
  const res = await fetch(`${API_BASE_URL}/v1/copilot/proposals`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Could not load proposals"));
  return (await res.json()) as PendingProposal[];
}

export async function listDecisionHistory(limit = 50, offset = 0): Promise<DecisionLogRow[]> {
  const res = await fetch(
    `${API_BASE_URL}/v1/copilot/decisions?limit=${limit}&offset=${offset}`,
    { headers: await authHeaders() },
  );
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Could not load decision history"));
  return (await res.json()) as DecisionLogRow[];
}

export async function approveProposal(
  proposalId: string,
): Promise<{ proposal_id: string; status: string }> {
  const res = await fetch(`${API_BASE_URL}/v1/copilot/proposals/${proposalId}/approve`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Approve failed"));
  return (await res.json()) as { proposal_id: string; status: string };
}

export async function rejectProposal(
  proposalId: string,
  reasonChip?: RejectReasonChip,
): Promise<{ proposal_id: string; status: string }> {
  const res = await fetch(`${API_BASE_URL}/v1/copilot/proposals/${proposalId}/reject`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ reason_chip: reasonChip ?? null }),
  });
  if (!res.ok) throw new Error(await deployErrorMessage(res, "Reject failed"));
  return (await res.json()) as { proposal_id: string; status: string };
}
