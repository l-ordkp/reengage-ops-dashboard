"use client";

import { useState } from "react";
import { FiSearch, FiCopy, FiCheck } from "react-icons/fi";
import PortalLoginLink from "@/components/shared/PortalLoginLink";
import { useAuth } from "@/providers/AuthProvider";
import { useReviewFilters } from "@/hooks/useReviews";
import api from "@/lib/api";
import { PRIORITY_COLOR, STATUS_COLOR, PRIORITY_ICON, STATUS_ICON, formatHoursLeft, formatIST, formatReviewDate } from "@/lib/constants";
import type { Review } from "@/lib/types";

type SearchMode = "by_id" | "by_customer";
type IdField = "review_uid" | "order_id" | "review_id" | "customer_id";

export default function SearchPage() {
  const { isLead } = useAuth();
  const { data: filterOpts } = useReviewFilters();

  const [mode, setMode] = useState<SearchMode>("by_id");
  const [idField, setIdField] = useState<IdField>("order_id");
  const [idValue, setIdValue] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [chain, setChain] = useState("");
  const [results, setResults] = useState<Review[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");

  if (!isLead) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        You do not have access to this page.
      </div>
    );
  }

  async function handleSearch() {
    setLoading(true);
    setSearched(true);
    setError("");
    try {
      const params: Record<string, string> = {};
      if (mode === "by_id") {
        params.field = idField;
        params.query = idValue.trim();
      } else {
        params.customer_name = customerName.trim();
        if (chain) params.chain_name = chain;
      }
      const { data } = await api.get("/api/reviews/search", { params });
      setResults(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Search Reviews</h1>
        <p className="text-gray-400 text-sm mt-1">Find reviews by ID or customer details</p>
      </div>

      {/* Mode Toggle */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="mode" checked={mode === "by_id"} onChange={() => setMode("by_id")} className="accent-blue-500" />
          <span className="text-sm text-gray-300">By ID</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="mode" checked={mode === "by_customer"} onChange={() => setMode("by_customer")} className="accent-blue-500" />
          <span className="text-sm text-gray-300">By Customer Name + Chain</span>
        </label>
      </div>

      {/* Search Inputs */}
      <div className="bg-[#262730] rounded-lg border border-gray-800 p-5">
        {mode === "by_id" ? (
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Field</label>
              <select value={idField} onChange={(e) => setIdField(e.target.value as IdField)}
                className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2">
                <option value="order_id">Order ID</option>
                <option value="review_uid">Review UID</option>
                <option value="review_id">Review ID</option>
                <option value="customer_id">Customer ID</option>
              </select>
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-gray-400 block mb-1">Value</label>
              <input type="text" value={idValue} onChange={(e) => setIdValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="Paste ID here..."
                className="w-full bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2" />
            </div>
            <button onClick={handleSearch} disabled={!idValue.trim() || loading}
              className="flex items-center gap-2 px-4 py-2 bg-[#FF4B4B] hover:bg-[#E04343] text-white text-sm font-medium rounded-lg disabled:opacity-50 cursor-pointer">
              <FiSearch size={15} />
              Search
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-gray-400 block mb-1">Customer Name</label>
              <input type="text" value={customerName} onChange={(e) => setCustomerName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="Customer name..."
                className="w-full bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Chain</label>
              <select value={chain} onChange={(e) => setChain(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2">
                <option value="">All Chains</option>
                {(filterOpts?.chains || []).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <button onClick={handleSearch} disabled={!customerName.trim() || loading}
              className="flex items-center gap-2 px-4 py-2 bg-[#FF4B4B] hover:bg-[#E04343] text-white text-sm font-medium rounded-lg disabled:opacity-50 cursor-pointer">
              <FiSearch size={15} />
              Search
            </button>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 text-sm rounded-lg p-3">{error}</div>
      )}

      {/* Results */}
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-[#262730] rounded-lg border border-gray-800 p-5 space-y-3 animate-pulse">
              <div className="h-5 bg-gray-800 rounded w-1/3" />
              <div className="h-4 bg-gray-800 rounded w-2/3" />
              <div className="h-4 bg-gray-800 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : searched && results.length === 0 && !error ? (
        <div className="bg-[#262730] rounded-lg border border-gray-800 p-12 text-center text-gray-500">
          No reviews found
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((r) => (
            <div key={r.review_uid} className="bg-[#262730] rounded-lg border border-gray-800 p-5 hover:border-gray-700 transition-colors">
              {/* Header */}
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <span className={`font-semibold text-sm ${PRIORITY_COLOR[r.priority] || ""}`}>
                  {PRIORITY_ICON[r.priority]} {r.priority}
                </span>
                <span className={`text-sm ${STATUS_COLOR[r.status] || ""}`}>
                  {STATUS_ICON[r.status]} {r.status}
                </span>
                <span className="text-sm text-yellow-400">{r.rating_display || r.star_rating}</span>
                <span className="text-sm text-gray-500">|</span>
                <span className="text-sm text-gray-400">{r.chain_name}</span>
                <span className="text-sm text-gray-400 capitalize">{r.platform}</span>
                {r.hours_left != null && (
                  <span className={`text-sm ${r.hours_left <= 24 ? "text-red-400" : "text-gray-400"}`}>
                    {formatHoursLeft(r.hours_left)} left
                  </span>
                )}
                <div className="ml-auto">
                  <PortalLoginLink review={r} />
                </div>
              </div>

              {/* Info grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm mb-3">
                <InfoField label="Customer" value={r.customer_name} />
                <InfoField label="Customer ID" value={r.customer_id} />
                <InfoField label="Type" value={r.customer_type} />
                <InfoField label="Review Date" value={formatReviewDate(r.review_date ? String(r.review_date) : null)} />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm mb-3">
                <InfoField label="Order ID" value={r.order_id} mono copyable />
                <InfoField label="Review ID" value={r.review_id} mono copyable />
                <InfoField label="Store ID" value={r.store_id} mono />
                <InfoField label="Order Value" value={r.order_value != null && r.order_value !== 0 ? `$${Number(r.order_value).toFixed(2)}` : null} />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm mb-3">
                <InfoField label="Last Assigned To" value={(r as any).assigned_to || "Unassigned"} />
                <InfoField label="Assignment Status" value={(r as any).assignment_status || null} />
                <InfoField label="Assigned At" value={formatIST((r as any).assigned_at)} />
                <InfoField label="Replied At" value={formatIST((r as any).completed_at)} />
                {(r as any).qc_response_match !== undefined && (
                  <InfoField label="Response Match" value={(r as any).qc_response_match ? "✅ Exact" : "⚠️ Mismatch"} />
                )}
                {(r as any).qc_discount_match !== undefined && (
                  <InfoField label="Discount Match" value={(r as any).qc_discount_match ? "✅ Exact" : "⚠️ Mismatch"} />
                )}
              </div>

              {/* Review text */}
              {r.review_text && (
                <div className="mb-3">
                  <p className="text-xs text-gray-500 mb-1">Review</p>
                  <p className="text-sm text-gray-300 bg-[#0E1117] rounded-lg p-3">{r.review_text}</p>
                </div>
              )}

              {/* AI Response with copy */}
              {r.response_text && (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-xs text-gray-500">AI Response</p>
                    <CopyTextButton text={r.response_text} />
                  </div>
                  <p className="text-sm text-green-300 bg-[#0E1117] rounded-lg p-3">{r.response_text}</p>
                  {r.coupon_value != null && Number(r.coupon_value) > 0 && (
                    <p className="text-xs text-yellow-400 mt-1">Coupon: ${Number(r.coupon_value).toFixed(2)}</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InfoField({ label, value, mono, copyable }: { label: string; value: string | null | undefined; mono?: boolean; copyable?: boolean }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <div className="flex items-center gap-1 group">
        <p className={`text-gray-300 truncate ${mono ? "font-mono text-xs" : "text-sm"}`}>
          {value || "-"}
        </p>
        {copyable && value && <CopyButton text={value} small />}
      </div>
    </div>
  );
}

function CopyTextButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-xs text-gray-300 transition-colors cursor-pointer">
      {copied ? <><FiCheck size={11} className="text-green-400" /> Copied</> : <><FiCopy size={11} /> Copy</>}
    </button>
  );
}

function CopyButton({ text, small }: { text: string; small?: boolean }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button onClick={handleCopy} title="Copy"
      className={`shrink-0 text-gray-500 hover:text-gray-300 transition-colors cursor-pointer ${small ? "opacity-0 group-hover:opacity-100" : ""}`}>
      {copied ? <FiCheck size={small ? 11 : 13} className="text-green-400" /> : <FiCopy size={small ? 11 : 13} />}
    </button>
  );
}
