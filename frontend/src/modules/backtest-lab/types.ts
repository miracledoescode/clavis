/** Backtest report payload returned by the engine (mirrors backtest_worker). */
export interface BacktestSummary {
  net_return: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy_r: number;
  trade_count: number;
}

export interface BacktestReport {
  report_version: string;
  summary: BacktestSummary;
  equity_curve: { time: number; value: number }[];
  meta: {
    symbol: string;
    timeframe: string;
    setups: number;
    bars: number;
    from: string;
    to: string;
    init_cash: number;
    costs: Record<string, number>;
    warnings: string[];
  };
  disclaimer: string;
}

export type BacktestStatus = "queued" | "running" | "done" | "error";

export interface BacktestRow {
  id: string;
  strategy_id: string;
  status: BacktestStatus;
  report?: BacktestReport | null;
  error?: string | null;
}
