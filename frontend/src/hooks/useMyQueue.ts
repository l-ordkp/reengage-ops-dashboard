"use client";

import { useCallback, useRef, useState } from "react";
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

const GENERATE_CHUNK_SIZE = 25;

interface ChunkResult {
  success: number;
  skipped: number;
  failed: number;
  details: { uid: string; status: string; reason?: string; note?: string }[];
}

interface GenerateProgress {
  done: number;
  total: number;
  success: number;
  skipped: number;
  failed: number;
}

export function useGenerateResponses() {
  const qc = useQueryClient();
  const [isPending, setIsPending] = useState(false);
  const [progress, setProgress] = useState<GenerateProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(
    async (reviewUids: string[], force = false) => {
      if (reviewUids.length === 0) return;

      const controller = new AbortController();
      abortRef.current = controller;
      setIsPending(true);
      setProgress({ done: 0, total: reviewUids.length, success: 0, skipped: 0, failed: 0 });

      const totals = { success: 0, skipped: 0, failed: 0 };
      try {
        for (let i = 0; i < reviewUids.length; i += GENERATE_CHUNK_SIZE) {
          if (controller.signal.aborted) break;
          const chunk = reviewUids.slice(i, i + GENERATE_CHUNK_SIZE);
          const { data } = await api.post<ChunkResult>(
            "/api/reviews/generate-batch",
            { review_uids: chunk, force },
            { signal: controller.signal },
          );
          totals.success += data.success;
          totals.skipped += data.skipped;
          totals.failed += data.failed;
          setProgress({
            done: Math.min(i + chunk.length, reviewUids.length),
            total: reviewUids.length,
            ...totals,
          });
          qc.invalidateQueries({ queryKey: ["my-queue"] });
          qc.invalidateQueries({ queryKey: ["reviews"] });
        }
      } finally {
        setIsPending(false);
        abortRef.current = null;
        qc.invalidateQueries({ queryKey: ["my-queue"] });
        qc.invalidateQueries({ queryKey: ["reviews"] });
        qc.invalidateQueries({ queryKey: ["review-stats"] });
      }
      return totals;
    },
    [qc],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { start, cancel, isPending, progress };
}
