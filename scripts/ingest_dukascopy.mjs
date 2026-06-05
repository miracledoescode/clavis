#!/usr/bin/env node
// ============================================================================
// Clavis OHLCV ingest — Dukascopy (free, no API key). One-time LOCAL setup.
//
// Writes {SYMBOL}_{TF}.csv (UTC timestamps) + a {SYMBOL}_{TF}.meta.json sidecar
// under BACKTEST_DATA_DIR. The VectorBT backtest worker reads these directly.
// Symbol set and date range are configurable — nothing is hardcoded.
//
//   cd scripts && npm install
//   BACKTEST_DATA_DIR=../data node ingest_dukascopy.mjs \
//     --symbols EURUSD,GBPUSD,XAUUSD --from 2020-01-01 --to 2025-01-01 --tf H1
//
// TIME: Dukascopy serves UTC. We pass utcOffset=0 and write ISO-8601 UTC
// timestamps, recording source_timezone="UTC" in the sidecar. Misaligned time is
// the classic backtest bug — everything here is normalized to UTC on ingest.
// ============================================================================

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { getHistoricalRates } from "dukascopy-node";

const DEFAULT_SYMBOLS = [
  "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD", "XAUUSD",
];
const TF_MAP = { M1: "m1", M5: "m5", M15: "m15", M30: "m30", H1: "h1", H4: "h4", D1: "d1", W1: "w1", MN1: "mn1" };

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const isoDate = (d) => d.toISOString().slice(0, 10);
const fiveYearsAgo = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 5);
  return isoDate(d);
};

const dataDir = process.env.BACKTEST_DATA_DIR || arg("out", "./data");
const symbols = arg("symbols", process.env.SYMBOLS || DEFAULT_SYMBOLS.join(","))
  .split(",")
  .map((s) => s.trim().toUpperCase())
  .filter(Boolean);
const tf = arg("tf", process.env.TIMEFRAME || "H1").toUpperCase();
const from = arg("from", process.env.FROM || fiveYearsAgo());
const to = arg("to", process.env.TO || isoDate(new Date()));

if (!TF_MAP[tf]) {
  console.error(`Unknown timeframe '${tf}'. One of: ${Object.keys(TF_MAP).join(", ")}`);
  process.exit(1);
}
mkdirSync(dataDir, { recursive: true });
console.log(`Ingest -> ${dataDir} | symbols=${symbols.join(",")} | tf=${tf} | ${from}..${to}`);

for (const symbol of symbols) {
  try {
    const rows = await getHistoricalRates({
      instrument: symbol.toLowerCase(),
      dates: { from: new Date(`${from}T00:00:00Z`), to: new Date(`${to}T00:00:00Z`) },
      timeframe: TF_MAP[tf],
      priceType: "bid",
      format: "json",
      volumes: true,
      utcOffset: 0, // keep timestamps in UTC
    });
    if (!rows || rows.length === 0) {
      console.warn(`  ${symbol}: no data returned`);
      continue;
    }
    const header = "timestamp,open,high,low,close,volume\n";
    const body = rows
      .map(
        (r) =>
          `${new Date(r.timestamp).toISOString()},${r.open},${r.high},${r.low},${r.close},${r.volume ?? 0}`,
      )
      .join("\n");
    writeFileSync(join(dataDir, `${symbol}_${tf}.csv`), header + body + "\n");
    writeFileSync(
      join(dataDir, `${symbol}_${tf}.meta.json`),
      JSON.stringify(
        {
          symbol,
          timeframe: tf,
          from,
          to,
          source: "dukascopy",
          source_timezone: "UTC",
          rows: rows.length,
          ingested_at: new Date().toISOString(),
        },
        null,
        2,
      ),
    );
    console.log(`  ${symbol}: ${rows.length} bars`);
  } catch (e) {
    console.error(`  ${symbol}: FAILED — ${e?.message || e}`);
  }
}
console.log("Done. Point the engine at this folder via BACKTEST_DATA_DIR.");
