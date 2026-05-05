"use client";

import { useState } from "react";
import { useAuth } from "@/providers/AuthProvider";
import {
  useOperatorPerformance,
  useDailyBreakdown,
  useChainBreakdown,
  useOperatorQueue,
} from "@/hooks/useOperators";
import { PRIORITY_ICON, STATUS_ICON } from "@/lib/constants";
import PortalLoginLink from "@/components/shared/PortalLoginLink";
import type { OperatorPerformance, DailyBreakdown, ChainBreakdown, Review } from "@/lib/types";

export default function OperatorsPage() {
  const { isLead } = useAuth();
  const { data: perfData, isLoading: perfLoading } = useOperatorPerformance();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dailyOperatorFilter, setDailyOperatorFilter] = useState("");
  const { data: dailyData } = useDailyBreakdown(dateFrom || undefined, dateTo || undefined);
  const [selectedChainOp, setSelectedChainOp] = useState("");
  const { data: chainData } = useChainBreakdown(selectedChainOp || undefined);
  const [selectedDrillOp, setSelectedDrillOp] = useState("");
  const { data: queueData } = useOperatorQueue(selectedDrillOp || undefined);
  const [expandedChains, setExpandedChains] = useState<Set<string>>(new Set());

  if (!isLead) return <div className="text-gray-400 p-8">Lead access required.</div>;

  const perf: OperatorPerformance[] = perfData || [];
  const daily: DailyBreakdown[] = dailyData || [];
  const chains: ChainBreakdown[] = chainData || [];
  const queueReviews: Review[] = queueData?.reviews || [];
  const queueCombos = queueData?.combos || [];

  const totalAssigned = perf.reduce((s, p) => s + p.total_assigned, 0);
  const totalCompleted = perf.reduce((s, p) => s + p.completed, 0);
  const totalExpired = perf.reduce((s, p) => s + p.expired, 0);
  const totalPending = perf.reduce((s, p) => s + p.pending, 0);
  const teamRate = totalCompleted + totalExpired > 0 ? (totalCompleted / (totalCompleted + totalExpired) * 100) : 0;

  const operatorEmails = perf.map((p) => p.operator_email).sort();

  function toggleChain(key: string) {
    setExpandedChains((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // Group chains by chain_name for collapse
  const chainGroups: Record<string, ChainBreakdown[]> = {};
  chains.forEach((c) => {
    if (!chainGroups[c.chain_name]) chainGroups[c.chain_name] = [];
    chainGroups[c.chain_name].push(c);
  });

  // Group queue reviews by chain+platform
  const reviewGroups: Record<string, Review[]> = {};
  queueReviews.forEach((r) => {
    const key = `${r.chain_name}/${r.platform}`;
    if (!reviewGroups[key]) reviewGroups[key] = [];
    reviewGroups[key].push(r);
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Operator Assignments Overview</h1>

      {/* Team metrics */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { label: "Total Assigned", value: totalAssigned },
          { label: "Pending", value: totalPending },
          { label: "Completed", value: totalCompleted },
          { label: "Expired", value: totalExpired },
          { label: "Team Completion", value: `${teamRate.toFixed(0)}%` },
        ].map((m) => (
          <div key={m.label} className="bg-[#262730] rounded-lg p-4">
            <p className="text-sm text-gray-400">{m.label}</p>
            <p className="text-2xl font-bold text-white">{m.value}</p>
          </div>
        ))}
      </div>

      {/* Performance table */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Operator Performance</h2>
        <p className="text-sm text-gray-400 mb-3">Last 14 days. Completion rate = completed / (completed + expired).</p>
        {perfLoading ? (
          <div className="animate-pulse bg-[#262730] rounded-lg h-48" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-[#262730] text-gray-400 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-3">Name</th>
                  <th className="text-left px-4 py-3">Email</th>
                  <th className="text-left px-4 py-3">Role</th>
                  <th className="px-4 py-3 text-right">Total</th>
                  <th className="px-4 py-3 text-right">Today</th>
                  <th className="px-4 py-3 text-right">Week</th>
                  <th className="px-4 py-3 text-right">Completed</th>
                  <th className="px-4 py-3 text-right">Missed</th>
                  <th className="px-4 py-3 text-right">Pending</th>
                  <th className="px-4 py-3 text-right">Completion %</th>
                </tr>
              </thead>
              <tbody>
                {perf.map((p) => (
                  <tr key={p.operator_email} className="border-t border-gray-800 hover:bg-[#262730]/50">
                    <td className="px-4 py-3 font-medium">{p.name || p.operator_email}</td>
                    <td className="px-4 py-3 text-gray-400">{p.operator_email}</td>
                    <td className="px-4 py-3 text-gray-400">{p.role}</td>
                    <td className="px-4 py-3 text-right">{p.total_assigned}</td>
                    <td className="px-4 py-3 text-right">{p.assigned_today}</td>
                    <td className="px-4 py-3 text-right">{p.assigned_this_week}</td>
                    <td className="px-4 py-3 text-right text-green-400">{p.completed}</td>
                    <td className="px-4 py-3 text-right text-red-400">{p.expired}</td>
                    <td className="px-4 py-3 text-right text-yellow-400">{p.pending}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-20 h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${p.completion_rate >= 80 ? "bg-green-500" : p.completion_rate >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                            style={{ width: `${Math.min(p.completion_rate || 0, 100)}%` }}
                          />
                        </div>
                        <span className="text-xs w-10 text-right">{(p.completion_rate || 0).toFixed(0)}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Date-wise completion */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Date-wise Completion</h2>
        <p className="text-sm text-gray-400 mb-3">Which operator missed the most reviews on which day.</p>
        <div className="flex gap-4 mb-4 flex-wrap">
          <div>
            <label className="text-xs text-gray-400 block mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Operator</label>
            <select value={dailyOperatorFilter} onChange={(e) => setDailyOperatorFilter(e.target.value)}
              className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm">
              <option value="">All Operators</option>
              {operatorEmails.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </div>
        </div>
        {daily.length > 0 ? (() => {
          const filteredDaily = dailyOperatorFilter
            ? daily.filter((d) => d.operator_email === dailyOperatorFilter)
            : daily;
          return filteredDaily.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-[#262730] text-gray-400 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-3">Date</th>
                  <th className="text-left px-4 py-3">Operator</th>
                  <th className="px-4 py-3 text-right">Assigned</th>
                  <th className="px-4 py-3 text-right">Completed</th>
                  <th className="px-4 py-3 text-right">Missed</th>
                  <th className="px-4 py-3 text-right">Pending</th>
                  <th className="px-4 py-3 text-right">Completion %</th>
                </tr>
              </thead>
              <tbody>
                {filteredDaily.map((d, i) => (
                  <tr key={i} className="border-t border-gray-800 hover:bg-[#262730]/50">
                    <td className="px-4 py-3">{String(d.assign_date)}</td>
                    <td className="px-4 py-3">{d.name || d.operator_email}</td>
                    <td className="px-4 py-3 text-right">{d.assigned}</td>
                    <td className="px-4 py-3 text-right text-green-400">{d.completed}</td>
                    <td className="px-4 py-3 text-right text-red-400">{d.expired}</td>
                    <td className="px-4 py-3 text-right text-yellow-400">{d.pending}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${(d.completion_pct || 0) >= 80 ? "bg-green-500" : (d.completion_pct || 0) >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                            style={{ width: `${Math.min(d.completion_pct || 0, 100)}%` }} />
                        </div>
                        <span className="text-xs">{(d.completion_pct || 0).toFixed(0)}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No data for selected filters.</p>
        ); })() : (
          <p className="text-gray-500 text-sm">No daily data available.</p>
        )}
      </div>

      {/* Chain breakdown */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Chain x Platform Breakdown</h2>
        <select value={selectedChainOp} onChange={(e) => setSelectedChainOp(e.target.value)}
          className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm mb-4">
          <option value="">Select operator</option>
          {operatorEmails.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        {Object.entries(chainGroups).map(([chainName, items]) => {
          const total = items.reduce((s, c) => s + c.assigned, 0);
          const done = items.reduce((s, c) => s + c.completed, 0);
          const missed = items.reduce((s, c) => s + c.expired, 0);
          const pend = items.reduce((s, c) => s + c.pending, 0);
          const rate = done + missed > 0 ? (done / (done + missed) * 100) : 0;
          const key = `chain-${chainName}`;
          const open = expandedChains.has(key);
          return (
            <div key={chainName} className="mb-2">
              <button onClick={() => toggleChain(key)}
                className="w-full flex items-center justify-between bg-[#262730] rounded-lg px-4 py-3 text-sm hover:bg-[#2f303a] cursor-pointer">
                <span className="font-medium">{chainName} — {total} assigned, {done} done, {missed} missed, {pend} pending ({rate.toFixed(0)}%)</span>
                <span className="text-gray-400">{open ? "▼" : "▶"}</span>
              </button>
              {open && (
                <div className="ml-4 mt-1 rounded-lg border border-gray-800 overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-[#262730] text-gray-400">
                      <tr>
                        <th className="text-left px-4 py-2">Platform</th>
                        <th className="px-4 py-2 text-right">Assigned</th>
                        <th className="px-4 py-2 text-right">Completed</th>
                        <th className="px-4 py-2 text-right">Missed</th>
                        <th className="px-4 py-2 text-right">Pending</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((c, i) => (
                        <tr key={i} className="border-t border-gray-800">
                          <td className="px-4 py-2">{c.platform}</td>
                          <td className="px-4 py-2 text-right">{c.assigned}</td>
                          <td className="px-4 py-2 text-right text-green-400">{c.completed}</td>
                          <td className="px-4 py-2 text-right text-red-400">{c.expired}</td>
                          <td className="px-4 py-2 text-right text-yellow-400">{c.pending}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Drill into queue */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Drill into Operator Queue</h2>
        <p className="text-sm text-gray-400 mb-3">View pending reviews grouped by chain and platform.</p>
        <select value={selectedDrillOp} onChange={(e) => setSelectedDrillOp(e.target.value)}
          className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm mb-4">
          <option value="">Select operator</option>
          {operatorEmails.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        {selectedDrillOp && queueCombos.length > 0 && (
          <div className="grid grid-cols-4 gap-3 mb-4">
            {queueCombos.map((c: any, i: number) => (
              <div key={i} className="bg-[#262730] rounded-lg p-3">
                <p className="text-xs text-gray-400">{c.chain_name} / {c.platform}</p>
                <p className="text-lg font-bold">{c.count} reviews</p>
                <p className={`text-xs ${c.min_days <= 2 ? "text-red-400" : "text-gray-400"}`}>{c.min_days}d left{c.critical > 0 ? ` (${c.critical} critical)` : ""}</p>
              </div>
            ))}
          </div>
        )}
        {Object.entries(reviewGroups).map(([groupKey, reviews]) => {
          const crits = reviews.filter((r) => r.priority === "CRITICAL").length;
          const minDays = Math.min(...reviews.map((r) => r.days_left));
          const key = `drill-${groupKey}`;
          const open = expandedChains.has(key) || crits > 0;
          return (
            <div key={groupKey} className="mb-2">
              <button onClick={() => toggleChain(key)}
                className="w-full flex items-center justify-between bg-[#262730] rounded-lg px-4 py-3 text-sm hover:bg-[#2f303a] cursor-pointer">
                <span className="font-medium">{groupKey} — {reviews.length} reviews, {minDays}d left{crits > 0 ? ` (${crits} critical)` : ""}</span>
                <span className="text-gray-400">{open ? "▼" : "▶"}</span>
              </button>
              {open && (
                <div className="ml-4 mt-1 overflow-x-auto rounded-lg border border-gray-800">
                  <table className="w-full text-sm">
                    <thead className="bg-[#262730] text-gray-400">
                      <tr>
                        <th className="text-left px-3 py-2">Priority</th>
                        <th className="text-left px-3 py-2">Days</th>
                        <th className="text-left px-3 py-2">Customer</th>
                        <th className="text-left px-3 py-2">Rating</th>
                        <th className="text-left px-3 py-2">Review</th>
                        <th className="text-left px-3 py-2">AI Response</th>
                        <th className="text-left px-3 py-2">Date</th>
                        <th className="px-3 py-2">Portal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reviews.map((r) => (
                        <tr key={r.review_uid} className="border-t border-gray-800">
                          <td className="px-3 py-2">{PRIORITY_ICON[r.priority]} {r.priority}</td>
                          <td className="px-3 py-2">{r.days_left}</td>
                          <td className="px-3 py-2">{r.customer_name || "—"}</td>
                          <td className="px-3 py-2">{r.rating_display}</td>
                          <td className="px-3 py-2 max-w-48 truncate">{r.review_text}</td>
                          <td className="px-3 py-2 max-w-48 truncate">{r.response_text || "—"}</td>
                          <td className="px-3 py-2 text-gray-400">{r.review_date}</td>
                          <td className="px-3 py-2"><PortalLoginLink review={r} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
