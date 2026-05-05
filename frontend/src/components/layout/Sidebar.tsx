"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  FiInbox,
  FiList,
  FiActivity,
  FiSettings,
  FiClipboard,
  FiSearch,
  FiUsers,
  FiUserCheck,
  FiMenu,
  FiX,
  FiLogOut,
  FiRefreshCw,
} from "react-icons/fi";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/providers/AuthProvider";
import { ROLE_LABELS } from "@/lib/constants";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  leadOnly?: boolean;
}

const navItems: NavItem[] = [
  { href: "/queue", label: "My Queue", icon: <FiInbox size={18} /> },
  { href: "/reviews", label: "All Reviews", icon: <FiList size={18} /> },
  { href: "/chain-health", label: "Chain Health", icon: <FiActivity size={18} /> },
  { href: "/configs", label: "Response Config", icon: <FiSettings size={18} /> },
  { href: "/ops-log", label: "Ops Log", icon: <FiClipboard size={18} /> },
];

const leadItems: NavItem[] = [
  { href: "/search", label: "Search Review", icon: <FiSearch size={18} />, leadOnly: true },
  { href: "/operators", label: "Operators", icon: <FiUsers size={18} />, leadOnly: true },
  { href: "/users", label: "Manage Users", icon: <FiUserCheck size={18} />, leadOnly: true },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, isLead, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const queryClient = useQueryClient();

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await api.post("/api/system/clear-cache");
      queryClient.invalidateQueries();
    } catch {}
    setRefreshing(false);
  }

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-gray-800">
        <h1 className="text-lg font-bold text-white tracking-tight">ReEngage Ops</h1>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            onClick={() => setMobileOpen(false)}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              isActive(item.href)
                ? "bg-[#FF4B4B]/20 text-[#FF4B4B]"
                : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
            }`}
          >
            {item.icon}
            {item.label}
          </Link>
        ))}

        {isLead && (
          <>
            <div className="pt-4 pb-2 px-3">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Lead Only
              </div>
            </div>
            {leadItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive(item.href)
                    ? "bg-[#FF4B4B]/20 text-[#FF4B4B]"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            ))}
          </>
        )}
      </nav>

      {/* User info */}
      {user && (
        <div className="px-4 py-4 border-t border-gray-800">
          <div className="mb-3">
            <p className="text-sm font-medium text-gray-200 truncate">{user.name}</p>
            <p className="text-xs text-gray-500">{ROLE_LABELS[user.role] || user.role}</p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-[#FF4B4B] transition-colors cursor-pointer mb-2"
          >
            <FiRefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Refreshing..." : "Refresh Data"}
          </button>
          <button
            onClick={logout}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-red-400 transition-colors cursor-pointer"
          >
            <FiLogOut size={15} />
            Sign Out
          </button>
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-4 left-4 z-50 p-2 rounded-lg bg-gray-800 text-gray-300 lg:hidden cursor-pointer"
        aria-label="Open menu"
      >
        <FiMenu size={20} />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-[#262730] border-r border-[#0E1117] transform transition-transform lg:hidden ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute top-4 right-4 p-1 text-gray-400 hover:text-gray-200 cursor-pointer"
          aria-label="Close menu"
        >
          <FiX size={20} />
        </button>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:flex-col lg:w-64 lg:shrink-0 bg-[#262730] border-r border-[#0E1117] h-screen sticky top-0">
        {sidebarContent}
      </aside>
    </>
  );
}
