"use client";

import { useOpsLog } from "@/hooks/useOpsLog";
import { formatIST } from "@/lib/constants";

export default function OpsLogPage() {
  const { data: entries, isLoading } = useOpsLog();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Ops Log</h1>
        <p className="text-gray-400 text-sm mt-1">Audit trail of all operations</p>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3 font-medium" title="Audit-log timestamp, shown in IST">Timestamp (IST)</th>
              <th className="px-4 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">Review UID</th>
              <th className="px-4 py-3 font-medium">Platform</th>
              <th className="px-4 py-3 font-medium">Chain</th>
              <th className="px-4 py-3 font-medium">Operator</th>
              <th className="px-4 py-3 font-medium">Performed By</th>
              <th className="px-4 py-3 font-medium min-w-[200px]">Remarks</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows cols={8} rows={10} />
            ) : !entries || entries.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-gray-500">
                  No log entries found
                </td>
              </tr>
            ) : (
              entries.map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                    {formatIST(e.processing_timestamp)}
                  </td>
                  <td className="px-4 py-3">
                    <ActionBadge action={e.action} />
                  </td>
                  <td className="px-4 py-3 text-gray-300 font-mono text-xs">
                    {e.review_uid || "-"}
                  </td>
                  <td className="px-4 py-3 text-gray-300 capitalize">{e.platform || "-"}</td>
                  <td className="px-4 py-3 text-gray-300">{e.chain_name || "-"}</td>
                  <td className="px-4 py-3 text-gray-300">{e.operator_email || "-"}</td>
                  <td className="px-4 py-3 text-gray-300">{e.performed_by || "-"}</td>
                  <td className="px-4 py-3 text-gray-400 max-w-[200px]">
                    <span className="line-clamp-2" title={e.remarks}>
                      {e.remarks || "-"}
                    </span>
                  </td>
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

function ActionBadge({ action }: { action: string }) {
  let color = "bg-gray-800 text-gray-300";
  const lower = action.toLowerCase();
  if (lower.includes("assign")) color = "bg-blue-900/40 text-blue-400";
  else if (lower.includes("complet") || lower.includes("respond")) color = "bg-green-900/40 text-green-400";
  else if (lower.includes("expire")) color = "bg-gray-700 text-gray-400";
  else if (lower.includes("generat")) color = "bg-purple-900/40 text-purple-400";
  else if (lower.includes("error") || lower.includes("fail")) color = "bg-red-900/40 text-red-400";

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {action}
    </span>
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
