"use client";

import { useState } from "react";

import type { StrategySpec } from "@/contract/types";
import { createStrategy, parseStrategy, updateStrategy } from "@/lib/api";

import { StrategyCanvas } from "./StrategyCanvas";
import type { ClarifyQuestion, MissingField } from "./types";

type Notice =
  | { kind: "clarification"; questions: ClarifyQuestion[] }
  | { kind: "block"; message: string }
  | { kind: "incomplete"; message: string; missing: MissingField[] }
  | { kind: "error"; message: string };

const PLACEHOLDER =
  "e.g. Go long EUR/USD on the H1 when price pulls back to the rising 200 EMA. " +
  "Risk 1% per trade, stop 1.5x ATR, take profit at 2R.";

export function RuleBuilder() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [spec, setSpec] = useState<StrategySpec | null>(null);
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  async function onParse() {
    if (!text.trim()) return;
    setBusy(true);
    setNotice(null);
    setSaveMsg(null);
    try {
      const res = await parseStrategy(text);
      if (res.type === "spec") {
        setSpec(res.spec);
        setStrategyId(null);
        setVersion(null);
      } else if (res.type === "clarification") {
        setNotice({ kind: "clarification", questions: res.questions });
      } else if (res.type === "block") {
        setNotice({ kind: "block", message: res.message });
      } else if (res.type === "incomplete") {
        setNotice({ kind: "incomplete", message: res.message, missing: res.missing });
      } else {
        setNotice({ kind: "error", message: res.message });
      }
    } catch (e) {
      setNotice({ kind: "error", message: e instanceof Error ? e.message : "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (!spec) return;
    setBusy(true);
    setSaveMsg(null);
    try {
      if (strategyId) {
        const row = await updateStrategy(strategyId, spec.name, spec);
        setVersion(row.version);
        setSaveMsg(`Saved. Version bumped to ${row.version}.`);
      } else {
        const row = await createStrategy(spec.name, spec);
        setStrategyId(row.id);
        setVersion(row.version);
        setSaveMsg(`Saved as version ${row.version}.`);
      }
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border p-4">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={3}
          className="w-full resize-y rounded border bg-background p-3 text-sm"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={onParse}
            disabled={busy || !text.trim()}
            className="rounded bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
          >
            {busy ? "Reading…" : "Build from description"}
          </button>
          <span className="text-xs text-muted-foreground">
            The Agent captures the logic you described — it never adds logic you didn&apos;t author.
          </span>
        </div>
      </div>

      {notice?.kind === "block" && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm">
          <strong className="text-destructive">Blocked.</strong> {notice.message}
        </div>
      )}
      {notice?.kind === "clarification" && (
        <div className="rounded-lg border p-4 text-sm">
          <strong>A few details are needed:</strong>
          <ul className="mt-2 list-disc pl-5">
            {notice.questions.map((q) => (
              <li key={q.id}>
                {q.question}
                {q.why ? <span className="text-muted-foreground"> — {q.why}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notice?.kind === "incomplete" && (
        <div className="rounded-lg border p-4 text-sm">
          <strong>{notice.message}</strong>
          <ul className="mt-2 list-disc pl-5">
            {notice.missing.map((m) => (
              <li key={m.field}>
                <code>{m.field}</code>: {m.problem}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notice?.kind === "error" && (
        <div className="rounded-lg border p-4 text-sm text-destructive">{notice.message}</div>
      )}

      {spec && (
        <div className="space-y-3">
          <StrategyCanvas spec={spec} onChange={setSpec} />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onSave}
              disabled={busy}
              className="rounded bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
            >
              {strategyId ? "Save edit (new version)" : "Save strategy"}
            </button>
            {version != null && (
              <span className="text-sm text-muted-foreground">Current version: {version}</span>
            )}
            {saveMsg && <span className="text-sm">{saveMsg}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
