"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ChainValueResponse } from "@/lib/types";

export function useManagedChains() {
  return useQuery<{ chains: string[] }>({
    queryKey: ["chain-value", "chains"],
    queryFn: async () => {
      const { data } = await api.get("/api/chain-value/chains");
      return data;
    },
  });
}

export function useChainValue(
  chain: string | null,
  startDate?: string | null,
  endDate?: string | null,
) {
  return useQuery<ChainValueResponse>({
    queryKey: ["chain-value", chain, startDate, endDate],
    queryFn: async () => {
      const { data } = await api.get("/api/chain-value", {
        params: {
          chain,
          start_date: startDate || undefined,
          end_date: endDate || undefined,
        },
      });
      return data;
    },
    enabled: !!chain,
  });
}
