"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import type { AuthUser } from "@/lib/types";

interface AuthContextType {
  user: AuthUser | null;
  loading: boolean;
  isLead: boolean;
  isManager: boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  isLead: false,
  isManager: false,
  logout: async () => {},
});

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    api
      .get("/api/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => {
        setUser(null);
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          router.push("/login");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      setUser(null);
      router.push("/login");
    }
  }, [router]);

  const isManager = user?.role === "manager";
  const isLead = user?.role === "lead" || isManager;

  return (
    <AuthContext.Provider value={{ user, loading, isLead, isManager, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
