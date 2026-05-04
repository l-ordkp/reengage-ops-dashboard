"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ReviewsResponse, ReviewStats } from "@/lib/types";

export interface ReviewFilters {
  chain_name?: string;
  platform?: string;
  status?: string;
  priority?: string;
  has_response?: string;
  page?: number;
  page_size?: number;
}

export function useReviews(filters: ReviewFilters = {}) {
  return useQuery<ReviewsResponse>({
    queryKey: ["reviews", filters],
    queryFn: async () => {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== "" && v !== null && v !== "All") params.append(k, String(v));
      });
      const { data } = await api.get(`/api/reviews?${params.toString()}`);
      return data;
    },
  });
}

export function useReviewStats(chain?: string) {
  return useQuery<ReviewStats>({
    queryKey: ["review-stats", chain],
    queryFn: async () => {
      const params = chain && chain !== "All" ? `?chain_name=${encodeURIComponent(chain)}` : "";
      const { data } = await api.get(`/api/reviews/stats${params}`);
      return data;
    },
  });
}

export function useReviewFilters() {
  return useQuery<{ chains: string[]; platforms: string[] }>({
    queryKey: ["review-filters"],
    queryFn: async () => {
      const { data } = await api.get("/api/reviews/filters");
      return data;
    },
  });
}
