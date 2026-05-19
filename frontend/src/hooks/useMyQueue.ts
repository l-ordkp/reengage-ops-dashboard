"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { Review, Assignment } from "@/lib/types";

interface MyQueueResponse {
  assignments: Assignment[];
  reviews: Review[];
}

export function useMyQueue() {
  return useQuery<MyQueueResponse>({
    queryKey: ["my-queue"],
    queryFn: async () => {
      const { data } = await api.get("/api/assignments/mine");
      return data;
    },
    staleTime: 2 * 60 * 1000,
  });
}

export function useMarkCompleted() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ assignmentId, remarks }: { assignmentId: string; remarks?: string }) => {
      const params = remarks ? `?remarks=${encodeURIComponent(remarks)}` : "";
      const { data } = await api.post(`/api/assignments/${assignmentId}/complete${params}`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-queue"] });
      qc.invalidateQueries({ queryKey: ["reviews"] });
      qc.invalidateQueries({ queryKey: ["review-stats"] });
    },
  });
}

// State lives in the provider so generation survives sidebar navigation.
export { useGenerateResponses } from "@/providers/GenerateResponsesProvider";
