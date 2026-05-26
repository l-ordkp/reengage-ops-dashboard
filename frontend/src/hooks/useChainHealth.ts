"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ChainHealthResponse } from "@/lib/types";

export function useChainHealth() {
  return useQuery<ChainHealthResponse>({
    queryKey: ["chain-health"],
    queryFn: async () => {
      const { data } = await api.get("/api/chain-health");
      return data;
    },
  });
}
