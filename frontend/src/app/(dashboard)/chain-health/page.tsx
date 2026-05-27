"use client";

import { useChainHealth } from "@/hooks/useChainHealth";

export default function ChainHealthPage() {
  const { data, isLoading } = useChainHealth();
  const summary = data?.summary;
  const chains = data?.chains ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Chain Health</h1>
        <p className="text-gray-400 text-sm mt-1">
          Last 14 days · ReEngage-managed chains only ·{" "}
          <span className="text-gray-500">
            total = out of scope + pending + responded + expired
          </span>
        </p>
      </div>

      {/* Headline */}
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 inline-block">
        <p className="text-xs text-gray-400 uppercase tracking-wider">Total Reviews</p>
        <p className="text-3xl font-bold mt-1 text-blue-400">
          {summary?.total != null ? summary.total.toLocaleString() : "—"}
        </p>
      </div>

      {/* Partition cards — these sum to Total Reviews */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Out of Scope" value={summary?.out_of_scope} color="text-gray-400"   />
        <MetricCard label="Pending"      value={summary?.pending}      color="text-yellow-400" />
        <MetricCard label="Responded"    value={summary?.responded}    color="text-green-400"  />
        <MetricCard label="Expired"      value={summary?.expired}      color="text-red-400"    />
      </div>

      {/* Subset card */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard
          label="Loop Responded"
          value={summary?.loop_responded}
          color="text-purple-400"
          subtitle="subset of Responded"
        />
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3 font-medium">Chain</th>
              <th className="px-4 py-3 font-medium text-right">Total</th>
              <th className="px-4 py-3 font-medium text-right">Out of Scope</th>
              <th className="px-4 py-3 font-medium text-right">In Scope</th>
              <th className="px-4 py-3 font-medium text-right">Pending</th>
              <th className="px-4 py-3 font-medium text-right">Responded</th>
              <th className="px-4 py-3 font-medium text-right">Loop Responded</th>
              <th className="px-4 py-3 font-medium text-right">Expired</th>
              <th className="px-4 py-3 font-medium text-right" title="Pending AND days_left <= 1 — act today">Critical</th>
              <th className="px-4 py-3 font-medium text-right" title="Pending AND days_left == 2 — act by tomorrow">Urgent</th>
              <th className="px-4 py-3 font-medium min-w-[160px]">Response Rate</th>
              <th className="px-4 py-3 font-medium min-w-[160px]">AI Coverage</th>
              <th className="px-4 py-3 font-medium text-right">Avg Rating</th>
              <th className="px-4 py-3 font-medium text-right">Locations</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows cols={14} rows={6} />
            ) : chains.length === 0 ? (
              <tr>
                <td colSpan={14} className="px-4 py-12 text-center text-gray-500">
                  No chain data available
                </td>
              </tr>
            ) : (
              chains.map((c) => (
                <tr
                  key={c.chain_name}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-gray-200">{c.chain_name}</td>
                  <td className="px-4 py-3 text-right text-blue-400">{c.total}</td>
                  <td className="px-4 py-3 text-right text-gray-400">{c.out_of_scope}</td>
                  <td className="px-4 py-3 text-right text-cyan-400">{c.in_scope}</td>
                  <td className="px-4 py-3 text-right text-yellow-400">{c.pending}</td>
                  <td className="px-4 py-3 text-right text-green-400">{c.responded}</td>
                  <td className="px-4 py-3 text-right text-purple-400">{c.loop_responded}</td>
                  <td className="px-4 py-3 text-right text-red-400">{c.expired}</td>
                  <td className="px-4 py-3 text-right text-red-500">{c.critical}</td>
                  <td className="px-4 py-3 text-right text-orange-400">{c.urgent}</td>
                  <td className="px-4 py-3">
                    <ProgressBar value={c.response_rate} color="bg-green-500" />
                  </td>
                  <td className="px-4 py-3">
                    <ProgressBar value={c.ai_coverage} color="bg-blue-500" />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-yellow-400">
                      {c.avg_rating != null ? c.avg_rating.toFixed(1) : "-"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">{c.locations}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function MetricCard({
  label,
  value,
  color,
  subtitle,
}: {
  label: string;
  value: number | undefined;
  color: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <p className="text-xs text-gray-400 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>
        {value != null ? value.toLocaleString() : "—"}
      </p>
      {subtitle && (
        <p className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">{subtitle}</p>
      )}
    </div>
  );
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  const pct = Math.min(100, Math.max(0, value ?? 0));
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

function SkeletonRows({ cols, rows }: { cols: number; rows: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="border-b border-gray-800/50">
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c} className="px-4 py-3">
              <div className="h-4 bg-gray-800 rounded animate-pulse" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
