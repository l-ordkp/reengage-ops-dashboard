"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { OperatorPerformance, DailyBreakdown, ChainBreakdown, Review } from "@/lib/types";

export function useOperatorPerformance() {
  return useQuery<OperatorPerformance[]>({
    queryKey: ["operator-performance"],
    queryFn: async () => {
      const { data } = await api.get("/api/operators/performance");
      return data;
    },
  });
}

export function useDailyBreakdown(from?: string, to?: string) {
  return useQuery<DailyBreakdown[]>({
    queryKey: ["daily-breakdown", from, to],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (from) params.append("date_from", from);
      if (to) params.append("date_to", to);
      const { data } = await api.get(`/api/operators/daily-breakdown?${params.toString()}`);
      return data;
    },
  });
}

export function useChainBreakdown(email?: string) {
  return useQuery<ChainBreakdown[]>({
    queryKey: ["chain-breakdown", email],
    queryFn: async () => {
      const params = email ? `?operator_email=${encodeURIComponent(email)}` : "";
      const { data } = await api.get(`/api/operators/chain-breakdown${params}`);
      return data;
    },
    enabled: !!email,
  });
}

interface OperatorQueueResponse {
  reviews: Review[];
  combos: { chain_name: string; platform: string; count: number; critical: number; min_days: number }[];
}

interface QCSummary {
  operator_email: string;
  name?: string;
  total_qc: number;
  resp_exact: number;
  disc_exact: number;
  resp_accuracy: number;
  disc_accuracy: number;
}

export interface QCMismatch {
  responded_at: string;
  operator_email: string;
  operator_name?: string;
  platform: string;
  chain_name: string;
  review_uid: string;
  customer_name?: string;
  resp_mismatch: boolean;
  disc_mismatch: boolean;
}

export function useQCMismatches(dateFrom?: string, dateTo?: string) {
  return useQuery<QCMismatch[]>({
    queryKey: ["qc-mismatches", dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);
      const qs = params.toString();
      const { data } = await api.get(`/api/operators/qc-mismatches${qs ? `?${qs}` : ""}`);
      return data;
    },
  });
}

export function useQCSummary(dateFrom?: string, dateTo?: string) {
  return useQuery<QCSummary[]>({
    queryKey: ["qc-summary", dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);
      const qs = params.toString();
      const { data } = await api.get(`/api/operators/qc-summary${qs ? `?${qs}` : ""}`);
      return data;
    },
  });
}

export function useOperatorQueue(email?: string) {
  return useQuery<OperatorQueueResponse>({
    queryKey: ["operator-queue", email],
    queryFn: async () => {
      const { data } = await api.get(`/api/operators/${encodeURIComponent(email!)}/queue`);
      return data;
    },
    enabled: !!email,
  });
}
