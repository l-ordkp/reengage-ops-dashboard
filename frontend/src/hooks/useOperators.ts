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

export function useQCSummary() {
  return useQuery<QCSummary[]>({
    queryKey: ["qc-summary"],
    queryFn: async () => {
      const { data } = await api.get("/api/operators/qc-summary");
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
