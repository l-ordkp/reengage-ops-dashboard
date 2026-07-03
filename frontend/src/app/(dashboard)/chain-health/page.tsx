"use client";

import { useChainHealth } from "@/hooks/useChainHealth";
import type { ChainHealthFlow, ChainHealthSummary } from "@/lib/types";

const n = (v: number | undefined | null) => (v != null ? v.toLocaleString() : "—");

function fmtDate(iso?: string, withYear = false): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}

export default function ChainHealthPage() {
  const { data, isLoading } = useChainHealth();
  const summary = data?.summary;
  const chains = data?.chains ?? [];
  const flow = data?.flow;

  const pending = summary?.pending ?? 0;
  const critical = summary?.critical ?? 0;
  const urgent = summary?.urgent ?? 0;
  const normal = Math.max(0, pending - critical - urgent);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Chain Health</h1>
        <p className="text-gray-400 text-sm mt-1">ReEngage-managed chains only</p>
      </div>

      {/* ══ 1 · NEEDS ATTENTION NOW — pending backlog by time left ══ */}
      <section className="space-y-4">
        <SectionHead
          dot="red"
          title="Needs attention now"
          pill="now"
          sub="In-scope reviews awaiting a reply, by time left — these add up to Open now."
        />
        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Open now</p>
          <p className="text-3xl font-bold mt-1 text-yellow-400 tabular-nums">{n(pending)}</p>
          <Bar total={pending} segs={[
            { label: "Critical", value: critical, color: "bg-red-500" },
            { label: "Urgent", value: urgent, color: "bg-orange-400" },
            { label: "Normal", value: normal, color: "bg-slate-500" },
          ]} />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <MetricCard label="Critical" value={critical} color="text-red-500" subtitle="≤ 1 day left" />
          <MetricCard label="Urgent" value={urgent} color="text-orange-400" subtitle="~ 2 days left" />
          <MetricCard label="Normal" value={normal} color="text-slate-300" subtitle="more than 2 days left" />
        </div>
      </section>

      {/* ══ 2 · THIS WEEK — replied & expired during the week ══ */}
      <section className="space-y-4">
        <SectionHead
          icon="📅"
          title="This week"
          pill="7d"
          meta={flow ? `${fmtDate(flow.period_start)} – ${fmtDate(flow.period_end, true)}` : "last 7 days"}
          sub="Reviews replied and expired during this week."
        />
        <div className="grid grid-cols-2 gap-4">
          <PlatformCard label="Replied" metric={flow?.solved} color="text-green-400" />
          <PlatformCard label="Expired" metric={flow?.missed} color="text-red-400" />
        </div>
      </section>

      {/* ══ 3 · LAST 14 DAYS — full standing status ══ */}
      <section className="space-y-4">
        <SectionHead
          dot="green"
          title="Last 14 days"
          pill="now"
          meta="live · refreshes ~every 5 min"
          sub="Every in-scope review posted in the last 14 days. Out of scope + Open now + Responded + Currently expired = Total."
        />
        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Total Reviews</p>
          <p className="text-3xl font-bold mt-1 text-blue-400 tabular-nums">{n(summary?.total)}</p>
          <Bar total={summary?.total ?? 0} legend segs={[
            { label: "Out of scope", value: summary?.out_of_scope ?? 0, color: "bg-gray-500" },
            { label: "Open now", value: pending, color: "bg-yellow-400" },
            { label: "Responded", value: summary?.responded ?? 0, color: "bg-green-400" },
            { label: "Currently expired", value: summary?.expired ?? 0, color: "bg-red-400" },
          ]} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Out of Scope" value={summary?.out_of_scope} color="text-gray-400" />
          <MetricCard label="Open now" value={pending} color="text-yellow-400" />
          <MetricCard label="Responded" value={summary?.responded} color="text-green-400" />
          <MetricCard label="Currently expired" value={summary?.expired} color="text-red-400" />
        </div>

        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className="sticky top-0 bg-gray-900 z-10">
              <tr className="border-b border-gray-800 text-left text-gray-400">
                <th className="px-4 py-3 font-medium">Chain</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium text-right">Out of Scope</th>
                <th className="px-4 py-3 font-medium text-right">In Scope</th>
                <th className="px-4 py-3 font-medium text-right">Open now</th>
                <th className="px-4 py-3 font-medium text-right">Responded</th>
                <th className="px-4 py-3 font-medium text-right">Loop Responded</th>
                <th className="px-4 py-3 font-medium text-right">Currently expired</th>
                <th className="px-4 py-3 font-medium text-right">Critical</th>
                <th className="px-4 py-3 font-medium text-right">Urgent</th>
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
                  <td colSpan={14} className="px-4 py-12 text-center text-gray-500">No chain data available</td>
                </tr>
              ) : (
                chains.map((c) => (
                  <tr key={c.chain_name} className="border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors">
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
                    <td className="px-4 py-3"><ProgressBar value={c.response_rate} color="bg-green-500" /></td>
                    <td className="px-4 py-3"><ProgressBar value={c.ai_coverage} color="bg-blue-500" /></td>
                    <td className="px-4 py-3 text-right"><span className="text-yellow-400">{c.avg_rating != null ? c.avg_rating.toFixed(1) : "-"}</span></td>
                    <td className="px-4 py-3 text-right text-gray-300">{c.locations}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function TimePill({ variant }: { variant: "now" | "7d" }) {
  const isNow = variant === "now";
  return (
    <span className={`inline-flex items-center text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
      isNow ? "bg-slate-800 text-slate-300 border-slate-600" : "bg-emerald-950 text-emerald-300 border-emerald-800"
    }`}>
      {isNow ? "now" : "7d"}
    </span>
  );
}

function SectionHead({
  title, pill, sub, meta, dot, icon,
}: {
  title: string;
  pill: "now" | "7d";
  sub?: string;
  meta?: string;
  dot?: "red" | "green";
  icon?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          {dot && <span className={`w-2.5 h-2.5 rounded-full ${dot === "red" ? "bg-red-500" : "bg-green-400"}`} />}
          {icon && <span className="text-base">{icon}</span>}
          <h2 className="text-lg font-bold text-white">{title}</h2>
          <TimePill variant={pill} />
        </div>
        {meta && <span className="text-xs text-gray-500">{meta}</span>}
      </div>
      {sub && <p className="text-[13px] text-gray-500">{sub}</p>}
    </div>
  );
}

function Bar({
  total, segs, legend,
}: {
  total: number;
  segs: { label: string; value: number; color: string }[];
  legend?: boolean;
}) {
  return (
    <div className="mt-3">
      <div className="flex gap-[2px] h-8 rounded-md overflow-hidden">
        {total > 0 &&
          segs.map((s) => (
            <div key={s.label} className={`${s.color} h-full`} style={{ width: `${(s.value / total) * 100}%` }} title={`${s.label}: ${s.value.toLocaleString()}`} />
          ))}
      </div>
      {legend && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11.5px] text-gray-400">
          {segs.map((s) => (
            <span key={s.label} className="inline-flex items-center gap-1.5">
              <i className={`inline-block w-2.5 h-2.5 rounded-sm ${s.color}`} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label, value, color, subtitle,
}: {
  label: string;
  value: number | undefined;
  color: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <p className="text-xs text-gray-400 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 tabular-nums ${color}`}>{value != null ? value.toLocaleString() : "—"}</p>
      {subtitle && <p className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">{subtitle}</p>}
    </div>
  );
}

function PlatformCard({
  label, metric, color,
}: {
  label: string;
  metric?: { total: number; doordash: number; ubereats: number };
  color: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <p className="text-xs text-gray-400 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 tabular-nums ${color}`}>{n(metric?.total)}</p>
      <p className="text-[11px] text-gray-500 mt-1 tabular-nums">DD {n(metric?.doordash)} · UE {n(metric?.ubereats)}</p>
    </div>
  );
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  const val = Math.min(100, Math.max(0, value ?? 0));
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${val}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{val.toFixed(0)}%</span>
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
