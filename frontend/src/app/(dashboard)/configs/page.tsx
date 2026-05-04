"use client";

import { FiPauseCircle, FiPlayCircle } from "react-icons/fi";
import { useConfigs } from "@/hooks/useConfigs";

export default function ConfigsPage() {
  const { data: configs, isLoading } = useConfigs();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Response Configs</h1>
        <p className="text-gray-400 text-sm mt-1">
          AI response generation configurations by chain
        </p>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-gray-900 rounded-lg border border-gray-800 p-5 space-y-3 animate-pulse">
              <div className="h-5 bg-gray-800 rounded w-2/3" />
              <div className="h-4 bg-gray-800 rounded w-1/2" />
              <div className="h-4 bg-gray-800 rounded w-3/4" />
              <div className="h-4 bg-gray-800 rounded w-1/3" />
            </div>
          ))}
        </div>
      ) : !configs || configs.length === 0 ? (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-12 text-center text-gray-500">
          No configs found
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {configs.map((cfg) => (
            <div
              key={cfg.config_id}
              className="bg-gray-900 rounded-lg border border-gray-800 p-5 space-y-3 hover:border-gray-700 transition-colors"
            >
              {/* Title Row */}
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-white">{cfg.config_name}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{cfg.chain_name}</p>
                </div>
                <span
                  className={`flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full ${
                    cfg.paused
                      ? "bg-red-900/40 text-red-400"
                      : "bg-green-900/40 text-green-400"
                  }`}
                >
                  {cfg.paused ? <FiPauseCircle size={12} /> : <FiPlayCircle size={12} />}
                  {cfg.paused ? "Paused" : "Active"}
                </span>
              </div>

              {/* Details */}
              <div className="space-y-1.5 text-sm">
                <ConfigRow label="Response Type" value={cfg.response_type} />
                <ConfigRow label="Tonality" value={cfg.tonality} />
                <ConfigRow
                  label="Platforms"
                  value={
                    Array.isArray(cfg.vb_platforms) ? cfg.vb_platforms.join(", ") : String(cfg.vb_platforms || "-")
                  }
                />
                <ConfigRow
                  label="Ratings"
                  value={
                    Array.isArray(cfg.ratings) ? cfg.ratings.join(", ") : String(cfg.ratings || "-")
                  }
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-300 text-right max-w-[60%] truncate">{value || "-"}</span>
    </div>
  );
}
