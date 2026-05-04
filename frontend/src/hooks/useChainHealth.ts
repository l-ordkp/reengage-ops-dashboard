"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ChainHealth } from "@/lib/types";

export function useChainHealth() {
  return useQuery<ChainHealth[]>({
    queryKey: ["chain-health"],
    queryFn: async () => {
      const { data } = await api.get("/api/chain-health");
      return data;
    },
  });
}
