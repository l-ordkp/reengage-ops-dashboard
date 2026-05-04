"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { User } from "@/lib/types";

export function useUsers() {
  return useQuery<User[]>({
    queryKey: ["users"],
    queryFn: async () => {
      const { data } = await api.get("/api/users");
      return data;
    },
  });
}

export function useAddUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { email: string; name: string; role: string; reduction_pct: number }) => {
      const { data } = await api.post("/api/users", payload);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ email, role, reduction_pct }: { email: string; role: string; reduction_pct: number }) => {
      const { data } = await api.put(`/api/users/${encodeURIComponent(email)}/role`, { role, reduction_pct });
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useToggleApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ email, approved }: { email: string; approved: boolean }) => {
      const { data } = await api.put(`/api/users/${encodeURIComponent(email)}/approval`, { approved });
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (email: string) => {
      const { data } = await api.delete(`/api/users/${encodeURIComponent(email)}`);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useRunAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (fullReassign: boolean) => {
      const { data } = await api.post("/api/system/run-assignment", { full_reassign: fullReassign });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reviews"] });
      qc.invalidateQueries({ queryKey: ["my-queue"] });
      qc.invalidateQueries({ queryKey: ["operator-performance"] });
    },
  });
}
