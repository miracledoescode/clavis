import { EquityChart } from "./equity-chart";
import type { BacktestReport } from "./types";

function pct(v: number, digits = 2): string {
  return `${(v * 100).toFixed(digits)}%`;
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "up" | "down" | "neutral";
}) {
  const color = tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="eyebrow mb-2">{label}</p>
      <p className={`numeric text-2xl font-medium ${color}`}>{value}</p>
    </div>
  );
}

/** Backtest report card. Numbers in IBM Plex Mono; up/down in muted brand colors;
 *  the disclaimer is always present (CLAUDE.md copy guardrail). */
export function ReportCard({ report }: { report: BacktestReport }) {
  const s = report.summary;
  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow mb-1">Backtest report</p>
        <h2 className="font-serif text-2xl font-medium">
          {report.meta.symbol} · {report.meta.timeframe}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {report.meta.bars.toLocaleString()} bars · {report.meta.from.slice(0, 10)} →{" "}
          {report.meta.to.slice(0, 10)} · {report.meta.setups} setup
          {report.meta.setups > 1 ? "s" : ""}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Metric label="Net return" value={pct(s.net_return)} tone={s.net_return >= 0 ? "up" : "down"} />
        <Metric label="Max drawdown" value={pct(s.max_drawdown)} tone="down" />
        <Metric label="Win rate" value={pct(s.win_rate, 1)} />
        <Metric label="Profit factor" value={s.profit_factor == null ? "∞" : s.profit_factor.toFixed(2)} />
        <Metric
          label="Expectancy"
          value={`${s.expectancy_r.toFixed(2)}R`}
          tone={s.expectancy_r >= 0 ? "up" : "down"}
        />
        <Metric label="Trades" value={String(s.trade_count)} />
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <p className="eyebrow mb-3">Equity curve</p>
        <EquityChart data={report.equity_curve} />
      </div>

      {report.meta.warnings.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 text-xs text-muted-foreground">
          <p className="eyebrow mb-2">Modelling notes</p>
          <ul className="list-disc space-y-1 pl-4">
            {report.meta.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-paper-deep p-4">
        <p className="eyebrow mb-2">Disclaimer</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{report.disclaimer}</p>
      </div>
    </div>
  );
}
