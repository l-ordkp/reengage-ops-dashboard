"use client";

import { useState } from "react";
import PortalLoginLink from "@/components/shared/PortalLoginLink";
import { useAuth } from "@/providers/AuthProvider";
import {
  useOperatorPerformance,
  useDailyBreakdown,
  useDailyIngested,
  useDailyLoopCompleted,
  useOperatorQueue,
  useQCMismatches,
  useQCSummary,
  type DailyIngested,
  type DailyLoopCompleted,
} from "@/hooks/useOperators";
import type { OperatorPerformance, DailyBreakdown, Review } from "@/lib/types";
import { PRIORITY_COLOR, STATUS_COLOR, PRIORITY_ICON, STATUS_ICON, formatHoursLeft, formatIST, formatReviewDate, todayIST } from "@/lib/constants";

export default function OperatorsPage() {
  const { isLead } = useAuth();
  const { data: perfData, isLoading: perfLoading } = useOperatorPerformance();
  const { data: dailyLoopData } = useDailyLoopCompleted();
  const { data: dailyIngestedData } = useDailyIngested();
  // Default the date-scoped tables (QC + Date-wise Completion) to the current
  // day so they don't render the full unbounded history on first load. Leads
  // can widen the range (or clear it) to pull everything. Computed in IST (the
  // operator workday) so a US-based lead doesn't get the wrong day at the IST
  // midnight boundary.
  const today = todayIST();
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [dailyOperatorFilter, setDailyOperatorFilter] = useState("");
  const { data: dailyData } = useDailyBreakdown(dateFrom || undefined, dateTo || undefined);
  const [selectedChainOp, setSelectedChainOp] = useState("");
  const { data: operatorQueue, isLoading: queueLoading } = useOperatorQueue(selectedChainOp || undefined);
  const [qcDateFrom, setQcDateFrom] = useState(today);
  const [qcDateTo, setQcDateTo] = useState(today);
  const { data: qcData } = useQCSummary(qcDateFrom || undefined, qcDateTo || undefined);
  const { data: mismatchData } = useQCMismatches(qcDateFrom || undefined, qcDateTo || undefined);
  const [mismatchOperator, setMismatchOperator] = useState("");
  const [mismatchType, setMismatchType] = useState<"" | "resp" | "disc" | "both">("");
  const [expandedChains, setExpandedChains] = useState<Set<string>>(new Set());

  if (!isLead) return <div className="text-gray-400 p-8">Lead access required.</div>;

  const perf: OperatorPerformance[] = perfData || [];
  const daily: DailyBreakdown[] = dailyData || [];
  const operatorReviews: Review[] = operatorQueue?.reviews || [];

  const totalAssigned = perf.reduce((s, p) => s + p.total_assigned, 0);
  const totalCompleted = perf.reduce((s, p) => s + p.completed, 0);
  const totalExpired = perf.reduce((s, p) => s + p.expired, 0);
  const totalPending = perf.reduce((s, p) => s + p.pending, 0);
  const teamRate = totalAssigned > 0 ? (totalCompleted / totalAssigned * 100) : 0;

  const operatorEmails = perf.map((p) => p.operator_email).sort();

  function toggleChain(key: string) {
    setExpandedChains((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // Group operator's pending reviews by chain
  const reviewsByChain: Record<string, Review[]> = {};
  operatorReviews.forEach((r) => {
    if (!reviewsByChain[r.chain_name]) reviewsByChain[r.chain_name] = [];
    reviewsByChain[r.chain_name].push(r);
  });
  // Sort chain names alphabetically for stable rendering
  const sortedChainNames = Object.keys(reviewsByChain).sort();


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

      {/* Daily Loop-completed (bars) overlaid with daily ingested (line).
          Lets a lead eyeball whether the team is keeping pace with intake. */}
      <DailyLoopChart
        data={dailyLoopData || []}
        ingested={dailyIngestedData || []}
      />

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
                  <th className="px-4 py-3 text-right">Expired</th>
                  <th className="px-4 py-3 text-right">Reassigned</th>
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
                    <td className="px-4 py-3 text-right text-blue-400">{(p as any).reassigned || 0}</td>
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

      {/* QC Accuracy */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Response QC Accuracy</h2>
        <p className="text-sm text-gray-400 mb-3">Did operators copy-paste the AI response and coupon correctly?</p>
        <div className="flex gap-4 mb-4 flex-wrap items-end">
          <DateRangeFilter
            from={qcDateFrom} to={qcDateTo}
            onFrom={setQcDateFrom} onTo={setQcDateTo}
            onClear={() => { setQcDateFrom(""); setQcDateTo(""); }}
          />
        </div>
        {qcData && qcData.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-[#262730] text-gray-400 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-3">Operator</th>
                  <th className="px-4 py-3 text-right">Total QC&apos;d</th>
                  <th className="px-4 py-3 text-right">Response Exact</th>
                  <th className="px-4 py-3 text-right">Response Accuracy</th>
                  <th className="px-4 py-3 text-right">Discount Exact</th>
                  <th className="px-4 py-3 text-right">Discount Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {qcData.map((q: any) => (
                  <tr key={q.operator_email} className="border-t border-gray-800 hover:bg-[#262730]/50">
                    <td className="px-4 py-3 font-medium">{q.name || q.operator_email}</td>
                    <td className="px-4 py-3 text-right">{q.total_qc}</td>
                    <td className="px-4 py-3 text-right text-green-400">{q.resp_exact}/{q.total_qc}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${q.resp_accuracy >= 90 ? "bg-green-500" : q.resp_accuracy >= 70 ? "bg-yellow-500" : "bg-red-500"}`}
                            style={{ width: `${Math.min(q.resp_accuracy || 0, 100)}%` }} />
                        </div>
                        <span className="text-xs">{(q.resp_accuracy || 0).toFixed(0)}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-green-400">{q.disc_exact}/{q.total_qc}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${q.disc_accuracy >= 90 ? "bg-green-500" : q.disc_accuracy >= 70 ? "bg-yellow-500" : "bg-red-500"}`}
                            style={{ width: `${Math.min(q.disc_accuracy || 0, 100)}%` }} />
                        </div>
                        <span className="text-xs">{(q.disc_accuracy || 0).toFixed(0)}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No QC data for the selected range.</p>
        )}
      </div>

      {/* QC Mismatches drilldown */}
      <div>
        <h2 className="text-lg font-semibold mb-3">QC Mismatches</h2>
        <p className="text-sm text-gray-400 mb-3">
          Reviews where the operator&apos;s response or discount did not match the AI
          suggestion. Uses the same date filter as Response QC Accuracy above. Use the
          Search tab with the <code>review_uid</code> to see the full AI response and
          posted text.
        </p>
        <div className="flex gap-4 mb-4 flex-wrap items-end">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Operator</label>
            <select value={mismatchOperator} onChange={(e) => setMismatchOperator(e.target.value)}
              className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm">
              <option value="">All Operators</option>
              {operatorEmails.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Mismatch Type</label>
            <select value={mismatchType}
              onChange={(e) => setMismatchType(e.target.value as "" | "resp" | "disc" | "both")}
              className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm">
              <option value="">Any</option>
              <option value="resp">Response only</option>
              <option value="disc">Discount only</option>
              <option value="both">Both</option>
            </select>
          </div>
        </div>
        {(() => {
          const rows = (mismatchData || []).filter((m) => {
            if (mismatchOperator && m.operator_email !== mismatchOperator) return false;
            if (mismatchType === "resp" && !(m.resp_mismatch && !m.disc_mismatch)) return false;
            if (mismatchType === "disc" && !(m.disc_mismatch && !m.resp_mismatch)) return false;
            if (mismatchType === "both" && !(m.resp_mismatch && m.disc_mismatch)) return false;
            return true;
          });
          if (rows.length === 0) {
            return <p className="text-gray-500 text-sm">No mismatches for the selected filters.</p>;
          }
          return (
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-sm">
                <thead className="bg-[#262730] text-gray-400 sticky top-0">
                  <tr>
                    <th className="text-left px-4 py-3" title="Operator's response timestamp, shown in IST">When (IST)</th>
                    <th className="text-left px-4 py-3">Operator</th>
                    <th className="text-left px-4 py-3">Chain · Platform</th>
                    <th className="text-left px-4 py-3">Customer</th>
                    <th className="text-left px-4 py-3">Review UID</th>
                    <th className="text-left px-4 py-3">Mismatch</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m, i) => (
                    <tr key={`${m.review_uid}-${i}`} className="border-t border-gray-800 align-top hover:bg-[#262730]/50">
                      <td className="px-4 py-3 text-gray-300 whitespace-nowrap">
                        {formatIST(m.responded_at)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">{m.operator_name || m.operator_email}</td>
                      <td className="px-4 py-3 text-gray-300 whitespace-nowrap">{m.chain_name} · {m.platform}</td>
                      <td className="px-4 py-3 whitespace-nowrap">{m.customer_name || "—"}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <button
                          onClick={() => navigator.clipboard.writeText(m.review_uid)}
                          title="Click to copy"
                          className="font-mono text-xs text-gray-300 hover:text-white px-2 py-1 rounded bg-gray-800/60 hover:bg-gray-700 cursor-pointer"
                        >
                          {m.review_uid}
                        </button>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {m.resp_mismatch && <span className="inline-block px-2 py-0.5 mr-1 rounded bg-red-900/40 text-red-300 text-xs">resp</span>}
                        {m.disc_mismatch && <span className="inline-block px-2 py-0.5 rounded bg-orange-900/40 text-orange-300 text-xs">disc</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })()}
      </div>

      {/* Date-wise completion */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Date-wise Completion</h2>
        <p className="text-sm text-gray-400 mb-3">Which operator missed the most reviews on which day.</p>
        <div className="flex gap-4 mb-4 flex-wrap items-end">
          <DateRangeFilter
            from={dateFrom} to={dateTo}
            onFrom={setDateFrom} onTo={setDateTo}
            onClear={() => { setDateFrom(""); setDateTo(""); }}
          />
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
                  <th className="text-left px-4 py-3" title="Assignment date in IST (operator workday)">Date (IST)</th>
                  <th className="text-left px-4 py-3">Operator</th>
                  <th className="px-4 py-3 text-right">Assigned</th>
                  <th className="px-4 py-3 text-right">Completed</th>
                  <th className="px-4 py-3 text-right">Expired</th>
                  <th className="px-4 py-3 text-right">Reassigned</th>
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
                    <td className="px-4 py-3 text-right text-blue-400">{(d as any).reassigned || 0}</td>
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

      {/* Chain x Platform breakdown — actual reviews from the operator's pending queue */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Chain x Platform Breakdown</h2>
        <p className="text-sm text-gray-400 mb-3">
          The operator&apos;s current pending assignments, grouped by chain. Shows the same review
          detail as their My Queue view.
        </p>
        <select value={selectedChainOp} onChange={(e) => setSelectedChainOp(e.target.value)}
          className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm mb-4">
          <option value="">Select operator</option>
          {operatorEmails.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        {!selectedChainOp ? (
          <p className="text-gray-500 text-sm">Pick an operator to see their pending reviews.</p>
        ) : queueLoading ? (
          <div className="animate-pulse bg-[#262730] rounded-lg h-32" />
        ) : sortedChainNames.length === 0 ? (
          <p className="text-gray-500 text-sm">No pending reviews for this operator.</p>
        ) : (
          sortedChainNames.map((chainName) => {
            const reviews = reviewsByChain[chainName];
            const critical = reviews.filter((r) => r.priority === "CRITICAL").length;
            const platforms = [...new Set(reviews.map((r) => r.platform))].sort().join(" · ");
            const key = `chain-${chainName}`;
            const open = expandedChains.has(key);
            return (
              <div key={chainName} className="mb-2">
                <button onClick={() => toggleChain(key)}
                  className="w-full flex items-center justify-between bg-[#262730] rounded-lg px-4 py-3 text-sm hover:bg-[#2f303a] cursor-pointer">
                  <span className="font-medium">
                    {chainName} — {reviews.length} pending ({platforms})
                    {critical > 0 && <span className="ml-2 text-red-400">· {critical} critical</span>}
                  </span>
                  <span className="text-gray-400">{open ? "▼" : "▶"}</span>
                </button>
                {open && (
                  <div className="ml-4 mt-1 rounded-lg border border-gray-800 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-[#262730] text-gray-400">
                        <tr>
                          <th className="text-left px-3 py-2">Priority</th>
                          <th className="text-left px-3 py-2">Status</th>
                          <th className="text-left px-3 py-2" title="Hours remaining until the platform deadline (timezone-agnostic)">Time Left</th>
                          <th className="text-left px-3 py-2">Platform</th>
                          <th className="text-left px-3 py-2">Customer</th>
                          <th className="text-left px-3 py-2">Rating</th>
                          <th className="text-left px-3 py-2 min-w-[200px]">Review</th>
                          <th className="text-left px-3 py-2 min-w-[200px]">AI Response</th>
                          <th className="text-left px-3 py-2" title="Customer's review date in restaurant local time (US/CT)">Review Date</th>
                          <th className="text-left px-3 py-2">Portal</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reviews.map((r) => (
                          <tr key={r.review_uid} className="border-t border-gray-800 align-top hover:bg-gray-800/40">
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={`font-semibold ${PRIORITY_COLOR[r.priority] || "text-gray-400"}`}>
                                {PRIORITY_ICON[r.priority]} {r.priority}
                              </span>
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={STATUS_COLOR[r.status] || "text-gray-400"}>
                                {STATUS_ICON[r.status]} {r.status}
                              </span>
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={r.hours_left <= 24 ? "text-red-400 font-semibold" : "text-gray-300"}>
                                {formatHoursLeft(r.hours_left)}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-gray-300 capitalize whitespace-nowrap">{r.platform}</td>
                            <td className="px-3 py-2 text-gray-300 whitespace-nowrap">{r.customer_name}</td>
                            <td className="px-3 py-2 text-yellow-400 whitespace-nowrap">
                              {r.rating_display || r.star_rating}
                            </td>
                            <td className="px-3 py-2 text-gray-300 max-w-[260px]">
                              <span className="line-clamp-2" title={r.review_text}>{r.review_text || "—"}</span>
                            </td>
                            <td className="px-3 py-2 max-w-[260px]">
                              {r.response_text ? (
                                <span className="line-clamp-2 text-green-300" title={r.response_text}>{r.response_text}</span>
                              ) : (
                                <span className="text-gray-600 italic">No response</span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-gray-400 whitespace-nowrap" title="Customer's review date in restaurant local time (US/CT)">
                              {formatReviewDate(r.review_date ? String(r.review_date) : null)}
                            </td>
                            <td className="px-3 py-2">
                              <PortalLoginLink review={r} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

    </div>
  );
}

// Shared From/To date-range filter with a Clear button (shown only once a
// bound is set). Used by both the QC and Date-wise Completion sections so they
// render and behave identically. Renders bare fields (no wrapper) so callers
// can place sibling filters in the same flex row.
function DateRangeFilter({
  from,
  to,
  onFrom,
  onTo,
  onClear,
}: {
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
  onClear: () => void;
}) {
  return (
    <>
      <div>
        <label className="text-xs text-gray-400 block mb-1">From</label>
        <input type="date" value={from} onChange={(e) => onFrom(e.target.value)}
          className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
      </div>
      <div>
        <label className="text-xs text-gray-400 block mb-1">To</label>
        <input type="date" value={to} onChange={(e) => onTo(e.target.value)}
          className="bg-[#262730] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
      </div>
      {(from || to) && (
        <div className="flex items-end">
          <button onClick={onClear}
            className="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 cursor-pointer">
            Clear
          </button>
        </div>
      )}
    </>
  );
}

// Daily Loop-completed (bars) + Daily ingested (line) for last 14 days.
// Bars: assignments.completed_at — each Loop-replied review counted once.
// Line: MIN(assigned_at) per review_uid — each review counted once on the
// day it first entered the assignment system. Line above bars = backlog
// growing; line at/below bars = team is keeping up. Both series get a
// dashed average reference line.
function DailyLoopChart({
  data,
  ingested,
}: {
  data: DailyLoopCompleted[];
  ingested: DailyIngested[];
}) {
  if (data.length === 0) {
    return (
      <div className="bg-[#262730] rounded-lg p-4 h-48 animate-pulse" />
    );
  }
  const ingestedByDate = new Map(ingested.map((i) => [i.date, i.ingested]));
  const ingestedSeries = data.map((d) => ingestedByDate.get(d.date) ?? 0);
  const max = Math.max(1, ...data.map((d) => d.loop_completed), ...ingestedSeries);
  const avg = Math.round(data.reduce((s, d) => s + d.loop_completed, 0) / data.length);
  const total = data.reduce((s, d) => s + d.loop_completed, 0);
  const ingestedTotal = ingestedSeries.reduce((s, v) => s + v, 0);
  const ingestedAvg = Math.round(ingestedTotal / data.length);

  const W = 760;
  const H = 220;
  const padL = 40;
  const padR = 16;
  const padT = 28;
  const padB = 36;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const slot = innerW / data.length;
  const barW = slot * 0.7;

  // iso is an IST date string from the backend (e.g. "2026-05-17"). Parse as
  // UTC and format as UTC so the label is identical regardless of the viewer's
  // browser timezone.
  const fmtDate = (iso: string) => {
    const d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  };

  return (
    <div className="bg-[#262730] rounded-lg p-4 border border-gray-800">
      <div className="flex items-baseline justify-between mb-3 gap-4">
        <div>
          <h2 className="text-lg font-semibold">Daily Loop: Ingested vs Completed</h2>
          <p className="text-xs text-gray-400">
            Last 14 days · IST. Bars = completed (completed_at).
            Line = newly ingested (first day in assignments).
          </p>
          <div className="flex gap-4 mt-2 text-xs">
            <span className="flex items-center gap-1.5 text-gray-300">
              <span className="inline-block w-3 h-3 rounded-sm bg-[#a78bfa]" /> Completed
            </span>
            <span className="flex items-center gap-1.5 text-gray-300">
              <span className="inline-block w-3 h-0.5 bg-[#38bdf8]" /> Ingested
            </span>
          </div>
        </div>
        <div className="text-right text-xs text-gray-400">
          <div>
            <span className="text-gray-500">completed 14d</span>{" "}
            <span className="text-white font-semibold">{total.toLocaleString()}</span>
            <span className="text-gray-500"> · avg/day </span>
            <span className="text-white font-semibold">{avg.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500">ingested 14d</span>{" "}
            <span className="text-white font-semibold">{ingestedTotal.toLocaleString()}</span>
            <span className="text-gray-500"> · avg/day </span>
            <span className="text-white font-semibold">{ingestedAvg.toLocaleString()}</span>
          </div>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {/* y-axis gridlines (4 ticks) */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = padT + innerH * (1 - t);
          const val = Math.round(max * t);
          return (
            <g key={t}>
              <line
                x1={padL} y1={y} x2={W - padR} y2={y}
                stroke="#374151" strokeWidth="1"
                strokeDasharray={t === 0 ? "0" : "2,3"}
              />
              <text
                x={padL - 6} y={y + 4}
                textAnchor="end" fontSize="10" fill="#9ca3af"
              >
                {val.toLocaleString()}
              </text>
            </g>
          );
        })}
        {/* bars: completed */}
        {data.map((d, i) => {
          const x = padL + slot * i + (slot - barW) / 2;
          const h = (d.loop_completed / max) * innerH;
          const y = padT + (innerH - h);
          return (
            <g key={d.date}>
              <rect
                x={x} y={y} width={barW} height={h}
                fill="#a78bfa"
                rx="2"
              >
                <title>{`${d.date}: ${d.loop_completed.toLocaleString()} completed`}</title>
              </rect>
              <text
                x={x + barW / 2} y={y - 4}
                textAnchor="middle" fontSize="10" fill="#e5e7eb"
              >
                {d.loop_completed.toLocaleString()}
              </text>
              <text
                x={x + barW / 2} y={padT + innerH + 14}
                textAnchor="middle" fontSize="10" fill="#9ca3af"
              >
                {fmtDate(d.date)}
              </text>
            </g>
          );
        })}
        {/* avg reference line — completed */}
        <line
          x1={padL} y1={padT + innerH * (1 - avg / max)}
          x2={W - padR} y2={padT + innerH * (1 - avg / max)}
          stroke="#f59e0b" strokeWidth="1" strokeDasharray="4,3"
        />
        <text
          x={W - padR - 4} y={padT + innerH * (1 - avg / max) - 4}
          textAnchor="end" fontSize="10" fill="#f59e0b"
        >
          avg completed {avg.toLocaleString()}
        </text>
        {/* avg reference line — ingested */}
        <line
          x1={padL} y1={padT + innerH * (1 - ingestedAvg / max)}
          x2={W - padR} y2={padT + innerH * (1 - ingestedAvg / max)}
          stroke="#38bdf8" strokeWidth="1" strokeDasharray="4,3"
        />
        <text
          x={padL + 4} y={padT + innerH * (1 - ingestedAvg / max) - 4}
          textAnchor="start" fontSize="10" fill="#38bdf8"
        >
          avg ingested {ingestedAvg.toLocaleString()}
        </text>
        {/* ingested line — one point per day, centered on the bar slot */}
        <polyline
          fill="none"
          stroke="#38bdf8"
          strokeWidth="2"
          points={data
            .map((_, i) => {
              const cx = padL + slot * i + slot / 2;
              const cy = padT + (innerH - (ingestedSeries[i] / max) * innerH);
              return `${cx},${cy}`;
            })
            .join(" ")}
        />
        {data.map((d, i) => {
          const cx = padL + slot * i + slot / 2;
          const cy = padT + (innerH - (ingestedSeries[i] / max) * innerH);
          return (
            <circle key={`ing-${d.date}`} cx={cx} cy={cy} r={3} fill="#38bdf8">
              <title>{`${d.date}: ${ingestedSeries[i].toLocaleString()} ingested`}</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}
