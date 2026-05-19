"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

const GENERATE_CHUNK_SIZE = 25;

interface ChunkResult {
  success: number;
  skipped: number;
  failed: number;
  details: { uid: string; status: string; reason?: string; note?: string }[];
}

export interface GenerateProgress {
  done: number;
  total: number;
  success: number;
  skipped: number;
  failed: number;
}

interface GenerateResponsesContextValue {
  start: (reviewUids: string[], force?: boolean) => Promise<{ success: number; skipped: number; failed: number } | undefined>;
  cancel: () => void;
  isPending: boolean;
  progress: GenerateProgress | null;
}

const GenerateResponsesContext = createContext<GenerateResponsesContextValue | null>(null);

export default function GenerateResponsesProvider({ children }: { children: React.ReactNode }) {
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

  return (
    <GenerateResponsesContext.Provider value={{ start, cancel, isPending, progress }}>
      {children}
    </GenerateResponsesContext.Provider>
  );
}

export function useGenerateResponses(): GenerateResponsesContextValue {
  const ctx = useContext(GenerateResponsesContext);
  if (!ctx) {
    throw new Error("useGenerateResponses must be used within GenerateResponsesProvider");
  }
  return ctx;
}
