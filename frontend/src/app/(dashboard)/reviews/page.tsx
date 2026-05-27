"use client";

import { useState, useCallback } from "react";
import { format } from "date-fns";
import { FiDownload, FiChevronLeft, FiChevronRight, FiCopy, FiCheck } from "react-icons/fi";
import { useReviews, useReviewFilters } from "@/hooks/useReviews";
import { PRIORITY_COLOR, STATUS_COLOR, PRIORITY_ICON, STATUS_ICON, formatHoursLeft } from "@/lib/constants";
import PortalLoginLink from "@/components/shared/PortalLoginLink";
import type { Review } from "@/lib/types";

const PAGE_SIZE = 50;

export default function ReviewsPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    chain_name: "",
    platform: "",
    status: "",
    priority: "",
  });

  const { data, isLoading } = useReviews({ ...filters, page, page_size: PAGE_SIZE });
  const { data: filterOpts } = useReviewFilters();

  const reviews = data?.items || [];
  const totalPages = Math.ceil((data?.total || 0) / PAGE_SIZE);

  function handleFilterChange(key: string, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  }

  const handleCSVDownload = useCallback(() => {
    if (!reviews.length) return;
    const headers = [
      "review_uid",
      "chain_name",
      "platform",
      "customer_name",
      "star_rating",
      "review_text",
      "response_text",
      "status",
      "priority",
      "hours_left",
      "review_date",
    ];
    const rows = reviews.map((r: Review) =>
      headers.map((h) => {
        const val = r[h as keyof Review];
        const str = val == null ? "" : String(val);
        return `"${str.replace(/"/g, '""')}"`;
      })
    );
    const csv = [headers.join(","), ...rows.map((r: string[]) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reviews_${format(new Date(), "yyyy-MM-dd")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [reviews]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">All Reviews</h1>
          <p className="text-gray-400 text-sm mt-1">
            {data?.total ?? 0} total reviews
          </p>
        </div>
        <button
          onClick={handleCSVDownload}
          disabled={!reviews.length}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm font-medium rounded-lg transition-colors disabled:opacity-40 cursor-pointer"
        >
          <FiDownload size={15} />
          Download CSV
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
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
          label="Status"
          value={filters.status}
          options={["PENDING", "RESPONDED", "EXPIRED"]}
          onChange={(v) => handleFilterChange("status", v)}
        />
        <FilterSelect
          label="Priority"
          value={filters.priority}
          options={["CRITICAL", "URGENT", "NORMAL"]}
          onChange={(v) => handleFilterChange("priority", v)}
        />
      </div>

      {/* Table */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">Order ID</th>
              <th className="px-4 py-3 font-medium">Review ID</th>
              <th className="px-4 py-3 font-medium">Priority</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Days Left</th>
              <th className="px-4 py-3 font-medium">Chain</th>
              <th className="px-4 py-3 font-medium">Platform</th>
              <th className="px-4 py-3 font-medium">Customer</th>
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Rating</th>
              <th className="px-4 py-3 font-medium min-w-[200px]">Review</th>
              <th className="px-4 py-3 font-medium min-w-[180px]">AI Response</th>
              <th className="px-4 py-3 font-medium">Order Value</th>
              <th className="px-4 py-3 font-medium">Date</th>
              <th className="px-4 py-3 font-medium">Portal</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows cols={16} rows={10} />
            ) : reviews.length === 0 ? (
              <tr>
                <td colSpan={16} className="px-4 py-12 text-center text-gray-500">
                  No reviews found
                </td>
              </tr>
            ) : (
              reviews.map((r, idx) => (
                <tr
                  key={r.review_uid}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-3 text-gray-500">
                    {(page - 1) * PAGE_SIZE + idx + 1}
                  </td>
                  <td className="px-4 py-3">
                    <CopyCell value={r.order_id} />
                  </td>
                  <td className="px-4 py-3">
                    <CopyCell value={r.review_id} />
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${PRIORITY_COLOR[r.priority] || ""}`}>
                      {PRIORITY_ICON[r.priority]} {r.priority}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={STATUS_COLOR[r.status] || ""}>
                      {STATUS_ICON[r.status]} {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={r.hours_left <= 24 ? "text-red-400 font-semibold" : "text-gray-300"}>
                      {formatHoursLeft(r.hours_left)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{r.chain_name}</td>
                  <td className="px-4 py-3 text-gray-300 capitalize">{r.platform}</td>
                  <td className="px-4 py-3 text-gray-300">{r.customer_name}</td>
                  <td className="px-4 py-3 text-gray-400">{r.customer_type}</td>
                  <td className="px-4 py-3">
                    <span className="text-yellow-400">{r.rating_display || r.star_rating}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-300 max-w-[200px]">
                    <span className="line-clamp-2" title={r.review_text}>
                      {r.review_text || "-"}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-[180px]">
                    {r.response_text ? (
                      <span className="line-clamp-2 text-green-300" title={r.response_text}>
                        {r.response_text}
                      </span>
                    ) : (
                      <span className="text-gray-600 italic">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {r.order_value != null ? `$${r.order_value.toFixed(2)}` : "-"}
                  </td>
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                    {r.review_date ? format(new Date(r.review_date), "MMM dd") : "-"}
                  </td>
                  <td className="px-4 py-3">
                    <PortalLoginLink review={r} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors disabled:opacity-40 cursor-pointer"
          >
            <FiChevronLeft size={16} />
            Previous
          </button>
          <span className="text-sm text-gray-400">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors disabled:opacity-40 cursor-pointer"
          >
            Next
            <FiChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
    >
      <option value="">All {label}</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

function CopyCell({ value }: { value: string | null }) {
  const [copied, setCopied] = useState(false);

  if (!value) return <span className="text-gray-600">-</span>;

  function handleCopy() {
    navigator.clipboard.writeText(value!);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <span className="inline-flex items-center gap-1 group max-w-[130px]">
      <span className="font-mono text-xs text-gray-400 truncate" title={value}>
        {value}
      </span>
      <button
        onClick={handleCopy}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-gray-500 hover:text-gray-300 cursor-pointer"
        title="Copy"
      >
        {copied ? <FiCheck size={12} className="text-green-400" /> : <FiCopy size={12} />}
      </button>
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
