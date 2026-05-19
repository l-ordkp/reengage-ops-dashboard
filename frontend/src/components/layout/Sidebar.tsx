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
import { useGenerateResponses } from "@/providers/GenerateResponsesProvider";
import { ROLE_LABELS } from "@/lib/constants";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  leadOnly?: boolean;
}

// Operator sees: My Queue only
const operatorItems: NavItem[] = [
  { href: "/queue", label: "My Queue", icon: <FiInbox size={18} /> },
];

// Lead sees: operator items + these
const leadItems: NavItem[] = [
  { href: "/reviews", label: "All Reviews", icon: <FiList size={18} /> },
  { href: "/chain-health", label: "Chain Health", icon: <FiActivity size={18} /> },
  { href: "/configs", label: "Response Config", icon: <FiSettings size={18} /> },
  { href: "/search", label: "Search Review", icon: <FiSearch size={18} /> },
  { href: "/operators", label: "Operators", icon: <FiUsers size={18} /> },
];

// Manager sees: lead items + these
const managerItems: NavItem[] = [
  { href: "/ops-log", label: "Ops Log", icon: <FiClipboard size={18} /> },
  { href: "/users", label: "Manage Users", icon: <FiUserCheck size={18} /> },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, isLead, isManager, logout } = useAuth();
  const generateResponses = useGenerateResponses();
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
        {operatorItems.map((item) => (
          <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClick={() => setMobileOpen(false)} />
        ))}

        {isLead && (
          <>
            <div className="pt-4 pb-2 px-3">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Lead
              </div>
            </div>
            {leadItems.map((item) => (
              <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClick={() => setMobileOpen(false)} />
            ))}
          </>
        )}

        {isManager && (
          <>
            <div className="pt-4 pb-2 px-3">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Manager
              </div>
            </div>
            {managerItems.map((item) => (
              <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClick={() => setMobileOpen(false)} />
            ))}
          </>
        )}
      </nav>

      {/* Generation status pill — visible from any dashboard page while a batch runs */}
      {generateResponses.isPending && generateResponses.progress && (
        <div className="mx-3 mb-3 px-3 py-2 rounded-lg bg-blue-900/30 border border-blue-800/50">
          <p className="text-xs text-blue-300 font-medium">
            Generating {generateResponses.progress.done} / {generateResponses.progress.total}
          </p>
          <button
            onClick={() => generateResponses.cancel()}
            className="text-xs text-gray-400 hover:text-red-400 mt-1 cursor-pointer"
          >
            Cancel
          </button>
        </div>
      )}

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

function NavLink({ item, isActive, onClick }: { item: NavItem; isActive: boolean; onClick: () => void }) {
  return (
    <Link
      href={item.href}
      onClick={onClick}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
        isActive
          ? "bg-[#FF4B4B]/20 text-[#FF4B4B]"
          : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
      }`}
    >
      {item.icon}
      {item.label}
    </Link>
  );
}
