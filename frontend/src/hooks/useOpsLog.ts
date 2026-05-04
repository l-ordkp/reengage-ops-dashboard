"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { OpsLogEntry } from "@/lib/types";

export function useOpsLog() {
  return useQuery<OpsLogEntry[]>({
    queryKey: ["ops-log"],
    queryFn: async () => {
      const { data } = await api.get("/api/ops-log");
      return data;
    },
  });
}
