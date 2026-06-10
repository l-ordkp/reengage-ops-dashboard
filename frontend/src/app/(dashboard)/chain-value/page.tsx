"use client";

import { useState } from "react";
import { useChainValue, useManagedChains } from "@/hooks/useChainValue";
import type { ChainValueRow } from "@/lib/types";

type Mode = "all" | "range";

export default function ChainValuePage() {
  const [chain, setChain] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("all");
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const chainsQuery = useManagedChains();
  const rangeReady = mode === "range" ? !!(startDate && endDate) : true;
  const valueQuery = useChainValue(
    rangeReady ? chain : null,
    mode === "range" ? startDate : null,
    mode === "range" ? endDate : null,
  );

  const chains = chainsQuery.data?.chains ?? [];
  const overall = valueQuery.data?.overall;
  const platforms = valueQuery.data?.platforms ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Chain Value</h1>
        <p className="text-gray-400 text-sm mt-1">
          Waterfall — total reviews, in-scope, responded, Loop responded.
        </p>
      </div>

      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 space-y-4">
        <div>
          <label className="block text-xs uppercase tracking-wider text-gray-400 mb-2">
            Chain
          </label>
          <select
            value={chain ?? ""}
            onChange={(e) => setChain(e.target.value || null)}
            disabled={chainsQuery.isLoading}
            className="w-full md:w-80 bg-gray-800 border border-gray-700 text-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-[#FF4B4B]"
          >
            <option value="">{chainsQuery.isLoading ? "Loading chains…" : "Select a chain"}</option>
            {chains.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs uppercase tracking-wider text-gray-400 mb-2">
            Range
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-md border border-gray-700 overflow-hidden">
              <ModeButton active={mode === "all"} onClick={() => setMode("all")}>
                Overall
              </ModeButton>
              <ModeButton active={mode === "range"} onClick={() => setMode("range")}>
                Date range
              </ModeButton>
            </div>
            {mode === "range" && (
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-[#FF4B4B]"
                />
                <span className="text-gray-500 text-sm">to</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-[#FF4B4B]"
                />
              </div>
            )}
          </div>
          {mode === "range" && !rangeReady && (
            <p className="text-gray-500 text-xs mt-2">Pick both dates to load the waterfall.</p>
          )}
        </div>
      </div>

      {!chain && (
        <p className="text-gray-500 text-sm">Pick a chain to see the waterfall.</p>
      )}

      {chain && valueQuery.isLoading && (
        <p className="text-gray-400 text-sm">Loading…</p>
      )}

      {chain && valueQuery.isError && (
        <p className="text-red-400 text-sm">
          {(valueQuery.error as Error)?.message || "Failed to load."}
        </p>
      )}

      {chain && (overall || platforms.length > 0) && (
        <>
          {overall && <Waterfall row={overall} title="Combined" />}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {platforms.map((p) => (
              <Waterfall key={p.platform ?? "unknown"} row={p} title={p.platform ?? "Unknown"} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Waterfall({ row, title }: { row: ChainValueRow; title: string }) {
  const total = row.total_reviews || 1; // avoid div/0
  const inScopeRate = pct(row.in_scope, row.total_reviews);
  const respondedRate = pct(row.responded, row.in_scope);
  const loopRate = pct(row.loop_responded, row.in_scope);

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-5 space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <span className="text-xs text-gray-500">
          {row.total_reviews.toLocaleString()} reviews
        </span>
      </div>

      <Bar
        label="Total"
        value={row.total_reviews}
        total={total}
        color="bg-blue-500"
      />
      <Bar
        label="In Scope"
        value={row.in_scope}
        total={total}
        color="bg-cyan-500"
        rateLabel={inScopeRate ? `${inScopeRate}% of total` : undefined}
      />
      <Bar
        label="Responded"
        value={row.responded}
        total={total}
        color="bg-green-500"
        rateLabel={respondedRate ? `${respondedRate}% of in-scope` : undefined}
      />
      <Bar
        label="Loop Responded"
        value={row.loop_responded}
        total={total}
        color="bg-purple-500"
        rateLabel={loopRate ? `${loopRate}% of in-scope` : undefined}
      />
    </div>
  );
}

function Bar({
  label,
  value,
  total,
  color,
  rateLabel,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
  rateLabel?: string;
}) {
  const width = total > 0 ? Math.min(100, (value / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-300">{label}</span>
        <span className="text-gray-200 font-medium">
          {value.toLocaleString()}
          {rateLabel && (
            <span className="text-gray-500 ml-2 text-xs">{rateLabel}</span>
          )}
        </span>
      </div>
      <div className="h-2 rounded bg-gray-800 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function pct(num: number, denom: number): string | null {
  if (!denom) return null;
  return ((num / denom) * 100).toFixed(1);
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-2 text-sm transition-colors cursor-pointer ${
        active
          ? "bg-[#FF4B4B]/20 text-[#FF4B4B]"
          : "bg-gray-800 text-gray-400 hover:text-gray-200"
      }`}
    >
      {children}
    </button>
  );
}
