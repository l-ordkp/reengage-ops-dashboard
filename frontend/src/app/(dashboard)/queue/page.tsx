"use client";

import { useState } from "react";
import { format } from "date-fns";
import { FiZap } from "react-icons/fi";
import PortalLoginLink from "@/components/shared/PortalLoginLink";
import { useMyQueue, useGenerateResponses } from "@/hooks/useMyQueue";
import { useReviewFilters, useReviewStats } from "@/hooks/useReviews";
import { PRIORITY_COLOR, STATUS_COLOR, PRIORITY_ICON, STATUS_ICON } from "@/lib/constants";
import type { Review } from "@/lib/types";

export default function QueuePage() {
  const [filters, setFilters] = useState({
    chain_name: "",
    platform: "",
    priority: "",
    status: "",
    has_response: "",
  });

  const { data, isLoading } = useMyQueue();
  const { data: filterOpts } = useReviewFilters();
  const generateResponses = useGenerateResponses();

  let reviews: Review[] = (data?.reviews || []).filter((r) => r.status !== "EXPIRED");

  const pendingCount = reviews.filter((r) => r.status === "PENDING").length;
  const criticalCount = reviews.filter((r) => r.priority === "CRITICAL").length;
  const missingAI = reviews.filter((r) => !r.response_text && r.status === "PENDING").length;

  function handleFilterChange(key: string, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  // Client-side filtering
  if (filters.chain_name) reviews = reviews.filter((r) => r.chain_name === filters.chain_name);
  if (filters.platform) reviews = reviews.filter((r) => r.platform === filters.platform);
  if (filters.priority) reviews = reviews.filter((r) => r.priority === filters.priority);
  if (filters.status) reviews = reviews.filter((r) => r.status === filters.status);
  if (filters.has_response === "true") reviews = reviews.filter((r) => r.response_text);
  if (filters.has_response === "false") reviews = reviews.filter((r) => !r.response_text);


  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">My Queue</h1>
        <p className="text-gray-400 text-sm mt-1">Reviews assigned to you for response posting</p>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Assigned" value={data?.reviews?.length ?? 0} color="text-blue-400" />
        <MetricCard label="Pending" value={pendingCount} color="text-yellow-400" />
        <MetricCard label="Critical" value={criticalCount} color="text-red-500" />
        <MetricCard label="Missing AI Response" value={missingAI} color="text-orange-400" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <FilterSelect
          label="Chain"
          value={filters.chain_name}
          options={filterOpts?.chains || []}
          onChange={(v) => handleFilterChange("chain_name", v)}
        />
        <FilterSelect
          label="Platform"
          value={filters.platform}
          options={filterOpts?.platforms || []}
          onChange={(v) => handleFilterChange("platform", v)}
        />
        <FilterSelect
          label="Priority"
          value={filters.priority}
          options={["CRITICAL", "URGENT", "NORMAL"]}
          onChange={(v) => handleFilterChange("priority", v)}
        />
        <FilterSelect
          label="Status"
          value={filters.status}
          options={["PENDING", "RESPONDED", "EXPIRED"]}
          onChange={(v) => handleFilterChange("status", v)}
        />
        <FilterSelect
          label="Has Response"
          value={filters.has_response}
          options={["true", "false"]}
          labels={["Yes", "No"]}
          onChange={(v) => handleFilterChange("has_response", v)}
        />

        {missingAI > 0 && (
          <button
            onClick={() => {
              const uids = (data?.reviews || []).filter((r) => !r.response_text && r.status === "PENDING").map((r) => r.review_uid);
              if (uids.length > 0) generateResponses.mutate(uids);
            }}
            disabled={generateResponses.isPending}
            className="ml-auto flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
          >
            <FiZap size={15} />
            {generateResponses.isPending ? "Generating..." : "Generate Responses"}
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">Priority</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Days Left</th>
              <th className="px-4 py-3 font-medium">Chain</th>
              <th className="px-4 py-3 font-medium">Platform</th>
              <th className="px-4 py-3 font-medium">Customer</th>
              <th className="px-4 py-3 font-medium">Rating</th>
              <th className="px-4 py-3 font-medium min-w-[200px]">Review</th>
              <th className="px-4 py-3 font-medium min-w-[200px]">AI Response</th>
              <th className="px-4 py-3 font-medium">Date</th>
              <th className="px-4 py-3 font-medium">Portal</th>
              <th className="px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows cols={13} rows={8} />
            ) : reviews.length === 0 ? (
              <tr>
                <td colSpan={13} className="px-4 py-12 text-center text-gray-500">
                  No reviews in your queue
                </td>
              </tr>
            ) : (
              reviews.map((r, idx) => (
                <tr
                  key={r.review_uid}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-3 text-gray-500">{idx + 1}</td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${PRIORITY_COLOR[r.priority] || "text-gray-400"}`}>
                      {PRIORITY_ICON[r.priority]} {r.priority}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`${STATUS_COLOR[r.status] || "text-gray-400"}`}>
                      {STATUS_ICON[r.status]} {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={r.days_left <= 1 ? "text-red-400 font-semibold" : "text-gray-300"}>
                      {r.days_left}d
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{r.chain_name}</td>
                  <td className="px-4 py-3 text-gray-300 capitalize">{r.platform}</td>
                  <td className="px-4 py-3 text-gray-300">{r.customer_name}</td>
                  <td className="px-4 py-3">
                    <span className="text-yellow-400">{r.rating_display || r.star_rating}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-300 max-w-[200px]">
                    <span className="line-clamp-2" title={r.review_text}>
                      {r.review_text || "-"}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-[200px]">
                    {r.response_text ? (
                      <span className="line-clamp-2 text-green-300" title={r.response_text}>
                        {r.response_text}
                      </span>
                    ) : (
                      <span className="text-gray-600 italic">No response</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                    {r.review_date ? format(new Date(r.review_date), "MMM dd") : "-"}
                  </td>
                  <td className="px-4 py-3">
                    <PortalLoginLink review={r} />
                  </td>
                  <td className="px-4 py-3">
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

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <p className="text-xs text-gray-400 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  labels,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  labels?: string[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
    >
      <option value="">All {label}</option>
      {options.map((opt, i) => (
        <option key={opt} value={opt}>
          {labels ? labels[i] : opt}
        </option>
      ))}
    </select>
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
