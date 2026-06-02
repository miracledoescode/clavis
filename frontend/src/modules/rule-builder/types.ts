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
 * Discriminated result of POST /strategies/parse. The JSON is the source of
 * truth; the canvas only ever renders a `spec` result.
 */
export type ParseResult =
  | { type: "spec"; spec: StrategySpec }
  | { type: "clarification"; questions: ClarifyQuestion[] }
  | { type: "block"; patterns: string[]; message: string }
  | { type: "incomplete"; missing: MissingField[]; message: string }
  | { type: "error"; message: string };
