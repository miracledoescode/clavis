import type { StrategySpec } from "@/contract/types";

/** A structured clarifying question returned by the parser. */
export interface ClarifyQuestion {
  id: string;
  question: string;
  why?: string;
  options?: string[];
}

export interface MissingField {
  field: string;
  problem: string;
}

/**
 * A setup's PROPOSED direction, awaiting user confirmation. The parser never
 * finalizes an inferred side — the Rule Builder confirms each one.
 */
export interface SetupDirectionInfo {
  index: number;
  name: string;
  direction: "long" | "short";
  inferred: boolean;
  rationale?: string;
}

/**
 * Discriminated result of POST /strategies/parse. The JSON is the source of
 * truth; the canvas only ever renders a `spec` result, and a spec is not
 * authored until every setup's direction is confirmed.
 */
export type ParseResult =
  | {
      type: "spec";
      spec: StrategySpec;
      setups: SetupDirectionInfo[];
      requires_direction_confirmation: boolean;
    }
  | { type: "clarification"; questions: ClarifyQuestion[] }
  | { type: "block"; patterns: string[]; message: string }
  | { type: "incomplete"; missing: MissingField[]; message: string }
  | { type: "error"; message: string };
