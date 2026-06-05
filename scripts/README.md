# Market data ingest (Dukascopy)

A **one-time, local** setup step that downloads OHLCV history for the FX majors +
XAUUSD and writes it where the backtest worker reads it. Dukascopy is free and
needs no API key.

This data is a **local store, never a broker feed** — the live engine never
pulls prices from here.

## Run it

```bash
cd scripts
npm install                     # installs dukascopy-node

# defaults: FX majors + XAUUSD, H1, last ~5 years
BACKTEST_DATA_DIR=../data node ingest_dukascopy.mjs

# or configure everything (nothing is hardcoded):
BACKTEST_DATA_DIR=../data node ingest_dukascopy.mjs \
  --symbols EURUSD,GBPUSD,XAUUSD \
  --from 2020-01-01 --to 2025-01-01 \
  --tf H1
```

Flags / env (flags win): `--symbols` / `SYMBOLS`, `--from` / `FROM`,
`--to` / `TO`, `--tf` / `TIMEFRAME`, `--out` / `BACKTEST_DATA_DIR`.

## Output

Per symbol+timeframe, under `BACKTEST_DATA_DIR`:

- `EURUSD_H1.csv` — `timestamp,open,high,low,close,volume`, timestamps in
  **ISO-8601 UTC**.
- `EURUSD_H1.meta.json` — provenance, including `source_timezone: "UTC"`.

## Time normalization (important)

Dukascopy serves data in **UTC**; the script passes `utcOffset: 0` and writes
UTC ISO timestamps. Misaligned time is the classic backtest bug, so everything is
normalized to UTC on ingest and the source timezone is recorded in the sidecar.

## Wire it to the engine

Point the FastAPI engine at the folder:

```bash
export BACKTEST_DATA_DIR=/abs/path/to/data
```

`backend/app/engine/backtest_data.py::load_ohlcv` reads `{SYMBOL}_{TF}.parquet`
or `{SYMBOL}_{TF}.csv` from that directory. (To store parquet instead of csv,
convert with pandas: `pd.read_csv(f).to_parquet(f.replace('.csv','.parquet'))`.)
