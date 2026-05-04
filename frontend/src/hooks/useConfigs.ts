"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ResponseConfig } from "@/lib/types";

export function useConfigs() {
  return useQuery<ResponseConfig[]>({
    queryKey: ["configs"],
    queryFn: async () => {
      const { data } = await api.get("/api/configs");
      return data;
    },
  });
}
