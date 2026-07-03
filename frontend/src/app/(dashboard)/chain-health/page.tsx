"use client";

import { useChainHealth } from "@/hooks/useChainHealth";
import type { ChainHealthFlow, ChainHealthSummary, FlowMetric } from "@/lib/types";

const n = (v: number | undefined | null) => (v != null ? v.toLocaleString() : "—");

function fmtDate(iso?: string, withYear = false): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
  });
}

export default function ChainHealthPage() {
  const { data, isLoading } = useChainHealth();
  const summary = data?.summary;
  const chains = data?.chains ?? [];
  const flow = data?.flow;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Chain Health</h1>
        <p className="text-gray-400 text-sm mt-1">ReEngage-managed chains only</p>
      </div>

      <NarrativeBanner summary={summary} flow={flow} />

      {/* Reading guide — persistent disambiguator */}
      <div className="text-sm text-gray-400 border border-gray-700 bg-gray-800/30 rounded-lg px-4 py-3">
        Two views below. <span className="text-slate-300 font-semibold">Right now</span> = the
        backlog as it stands{" "}
        <span className="text-gray-500">(these numbers add up to Total)</span>.{" "}
        <span className="text-emerald-300 font-semibold">This week</span> = what happened in the
        last 7 days <span className="text-gray-500">(independent tallies)</span>. A review can
        appear in both — never add the two together.
      </div>

      {/* ══════════ SECTION A — RIGHT NOW (stock) ══════════ */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-green-400 shadow-[0_0_0_4px_rgba(74,222,128,0.18)]" />
            <h2 className="text-lg font-bold text-white">Right now</h2>
            <TimePill variant="now" />
          </div>
          <span className="text-xs text-gray-500">live · refreshes ~every 5 min</span>
        </div>
        <p className="text-[13px] text-gray-400 -mt-2">
          Live status of every in-scope review posted in the last 14 days. Out of scope + Open now +
          Responded + Currently expired = Total.
        </p>

        {/* Total + stacked partition bar */}
        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Total Reviews</p>
          <p className="text-3xl font-bold mt-1 text-blue-400 tabular-nums">{n(summary?.total)}</p>
          <StackedBar summary={summary} />
        </div>

        {/* Partition cards — sum to Total */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Out of Scope" value={summary?.out_of_scope} color="text-gray-400" pill="now" subtitle="chain rules filter these out" />
          <MetricCard label="Open now" value={summary?.pending} color="text-yellow-400" pill="now" subtitle="in scope · no reply · deadline open" />
          <MetricCard label="Responded" value={summary?.responded} color="text-green-400" pill="now" subtitle="in scope · already replied" />
          <MetricCard label="Currently expired" value={summary?.expired} color="text-red-400" pill="now" subtitle="in scope · past deadline · still unanswered" />
        </div>

        {/* Subset cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Critical" value={summary?.critical} color="text-red-500" subset subtitle="subset of Open now · ≤1 day left" />
          <MetricCard label="Urgent" value={summary?.urgent} color="text-orange-400" subset subtitle="subset of Open now · ~2 days left" />
          <MetricCard label="Loop Responded" value={summary?.loop_responded} color="text-purple-400" subset subtitle="subset of Responded" />
        </div>

        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className="sticky top-0 bg-gray-900 z-10">
              <tr className="border-b border-gray-800 text-left text-gray-400">
                <th className="px-4 py-3 font-medium">Chain <span className="text-gray-600 font-normal">· snapshot as of now</span></th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium text-right">Out of Scope</th>
                <th className="px-4 py-3 font-medium text-right">In Scope</th>
                <th className="px-4 py-3 font-medium text-right">Open now</th>
                <th className="px-4 py-3 font-medium text-right">Responded</th>
                <th className="px-4 py-3 font-medium text-right">Loop Responded</th>
                <th className="px-4 py-3 font-medium text-right text-red-400/90" title="Past deadline and still unanswered as of now — the live backlog. NOT 'Deadlines missed' this week.">Expired now</th>
                <th className="px-4 py-3 font-medium text-right" title="Open now AND hours_left ≤ 24 — act within 24h">Critical</th>
                <th className="px-4 py-3 font-medium text-right" title="Open now AND 24 &lt; hours_left ≤ 48 — act within 48h">Urgent</th>
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

      {/* ══════════ DIVIDER ══════════ */}
      <div className="flex items-center gap-4 text-gray-600 py-2">
        <hr className="flex-1 border-gray-700" />
        <span className="text-[11px] uppercase tracking-[0.12em] text-gray-500 border border-gray-700 rounded-full px-3 py-1">
          ▽ different clock ▽
        </span>
        <hr className="flex-1 border-gray-700" />
      </div>

      {/* ══════════ SECTION B — THIS WEEK (flow) ══════════ */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="text-base">📅</span>
            <h2 className="text-lg font-bold text-white">This week</h2>
            <TimePill variant="7d" />
          </div>
          <span className="text-xs text-gray-500">
            {flow ? `${fmtDate(flow.period_start)} – ${fmtDate(flow.period_end, true)}` : "last 7 days"}
          </span>
        </div>
        <p className="text-[13px] text-gray-400 -mt-2">
          Events in the last 7 days, each counted on the day it happened. Three separate tallies —
          they do not add up to New reviews.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <FlowTile label="New reviews" metric={flow?.ingested} color="text-cyan-400" caption="posted this week" />
          <FlowTile label="Solved" metric={flow?.solved} color="text-green-400" caption="Loop-completed this week" />
          <FlowTile label="Deadlines missed" metric={flow?.missed} color="text-red-400" caption="reply window closed this week" />
        </div>
        <p className="text-xs text-gray-500">
          Independent counts — <span className="text-gray-400">not a breakdown of New reviews</span>.
          &ldquo;Pending&rdquo; isn&rsquo;t shown here — it&rsquo;s a live status, see{" "}
          <span className="text-slate-300">Right now</span> above.
        </p>
      </section>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function TimePill({ variant }: { variant: "now" | "7d" }) {
  const isNow = variant === "now";
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
        isNow
          ? "bg-slate-800 text-slate-300 border-slate-600"
          : "bg-emerald-950 text-emerald-300 border-emerald-800"
      }`}
    >
      {isNow ? "now" : "7d"}
    </span>
  );
}

function NarrativeBanner({
  summary,
  flow,
}: {
  summary?: ChainHealthSummary;
  flow?: ChainHealthFlow;
}) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 space-y-1.5">
      <p className="text-[15px] text-gray-200">
        This week{" "}
        <b className="text-emerald-400">{n(flow?.ingested.total)}</b> new reviews came in — Loop
        solved <b className="text-emerald-400">{n(flow?.solved.total)}</b>, and{" "}
        <b className="text-emerald-400">{n(flow?.missed.total)}</b> slipped past their deadline
        unanswered.
      </p>
      <p className="text-[15px] text-gray-200">
        Right now <b className="text-yellow-400">{n(summary?.pending)}</b> in-scope reviews are still
        waiting for a reply — <b className="text-red-400">{n(summary?.critical)}</b> of them critical
        (under 24 hours left).
      </p>
      <p className="text-[11px] text-gray-500 pt-1">
        ⓘ Two clocks. <b>This week</b> counts events in the last 7 days. <b>Right now</b> counts
        reviews sitting in the queue this moment. They measure different things — don&rsquo;t add them
        together.
      </p>
    </div>
  );
}

function StackedBar({ summary }: { summary?: ChainHealthSummary }) {
  const total = summary?.total ?? 0;
  const segs = [
    { label: "Out of scope", value: summary?.out_of_scope ?? 0, color: "bg-gray-500" },
    { label: "Open now", value: summary?.pending ?? 0, color: "bg-yellow-400" },
    { label: "Responded", value: summary?.responded ?? 0, color: "bg-green-400" },
    { label: "Currently expired", value: summary?.expired ?? 0, color: "bg-red-400" },
  ];
  return (
    <div className="mt-3">
      <div className="flex gap-[2px] h-8 rounded-md overflow-hidden">
        {total > 0 &&
          segs.map((s) => (
            <div
              key={s.label}
              className={`${s.color} h-full`}
              style={{ width: `${(s.value / total) * 100}%` }}
              title={`${s.label}: ${s.value.toLocaleString()}`}
            />
          ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11.5px] text-gray-400">
        {segs.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <i className={`inline-block w-2.5 h-2.5 rounded-sm ${s.color}`} />
            {s.label}
          </span>
        ))}
        <span className="ml-auto text-gray-500">▸ segments add to Total</span>
      </div>
    </div>
  );
}

function FlowTile({
  label,
  metric,
  color,
  caption,
}: {
  label: string;
  metric?: FlowMetric;
  color: string;
  caption: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-gray-700 p-4 bg-transparent">
      <p className="text-xs text-gray-400 uppercase tracking-wider flex items-center justify-between gap-2">
        {label}
        <TimePill variant="7d" />
      </p>
      <p className={`text-3xl font-bold mt-1.5 tabular-nums ${color}`}>{n(metric?.total)}</p>
      <p className="text-[11.5px] text-gray-500 mt-1.5 tabular-nums">
        DD {n(metric?.doordash)} · UE {n(metric?.ubereats)}
      </p>
      <p className="text-[10px] text-gray-600 mt-1.5 uppercase tracking-wider">{caption}</p>
    </div>
  );
}

function MetricCard({
  label,
  value,
  color,
  subtitle,
  pill,
  subset,
}: {
  label: string;
  value: number | undefined;
  color: string;
  subtitle?: string;
  pill?: "now" | "7d";
  subset?: boolean;
}) {
  return (
    <div className={`rounded-lg p-4 border ${subset ? "bg-gray-900/40 border-dashed border-gray-700" : "bg-gray-900 border-gray-800"}`}>
      <p className="text-xs text-gray-400 uppercase tracking-wider flex items-center justify-between gap-2">
        {label}
        {pill && <TimePill variant={pill} />}
      </p>
      <p className={`text-2xl font-bold mt-1 tabular-nums ${color}`}>
        {value != null ? value.toLocaleString() : "—"}
      </p>
      {subtitle && <p className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">{subtitle}</p>}
    </div>
  );
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  const pct = Math.min(100, Math.max(0, value ?? 0));
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
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
