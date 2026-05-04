"use client";

import { useChainHealth } from "@/hooks/useChainHealth";

export default function ChainHealthPage() {
  const { data: chains, isLoading } = useChainHealth();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Chain Health</h1>
        <p className="text-gray-400 text-sm mt-1">
          Overview of response coverage and performance by chain
        </p>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3 font-medium">Chain</th>
              <th className="px-4 py-3 font-medium text-right">Total</th>
              <th className="px-4 py-3 font-medium text-right">Responded</th>
              <th className="px-4 py-3 font-medium text-right">Pending</th>
              <th className="px-4 py-3 font-medium text-right">Expired</th>
              <th className="px-4 py-3 font-medium text-right">Critical</th>
              <th className="px-4 py-3 font-medium min-w-[160px]">Response Rate</th>
              <th className="px-4 py-3 font-medium min-w-[160px]">AI Coverage</th>
              <th className="px-4 py-3 font-medium text-right">Avg Rating</th>
              <th className="px-4 py-3 font-medium text-right">Locations</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows cols={10} rows={6} />
            ) : !chains || chains.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-12 text-center text-gray-500">
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
                  <td className="px-4 py-3 text-right text-gray-300">{c.total}</td>
                  <td className="px-4 py-3 text-right text-green-400">{c.responded}</td>
                  <td className="px-4 py-3 text-right text-yellow-400">{c.pending}</td>
                  <td className="px-4 py-3 text-right text-gray-500">{c.expired}</td>
                  <td className="px-4 py-3 text-right text-red-400">{c.critical}</td>
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

function ProgressBar({ value, color }: { value: number; color: string }) {
  const pct = Math.min(100, Math.max(0, (value ?? 0) * 100));
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
