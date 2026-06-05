"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, type UTCTimestamp } from "lightweight-charts";

/** Equity curve via TradingView Lightweight Charts. attributionLogo enabled
 *  (Apache-2.0 license requirement / CLAUDE.md). Brand gold fill, muted axes. */
export function EquityChart({ data }: { data: { time: number; value: number }[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(83, 75, 62, 0.85)",
        fontFamily: "var(--font-plex-mono), monospace",
        fontSize: 11,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(120, 100, 60, 0.12)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
      crosshair: { horzLine: { visible: false }, vertLine: { labelVisible: false } },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#C2952B",
      topColor: "rgba(194, 149, 43, 0.28)",
      bottomColor: "rgba(194, 149, 43, 0.02)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(data.map((d) => ({ time: d.time as UTCTimestamp, value: d.value })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return <div ref={containerRef} className="h-[280px] w-full" />;
}
