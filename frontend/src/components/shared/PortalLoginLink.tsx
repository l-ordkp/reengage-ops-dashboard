"use client";

import { FiExternalLink } from "react-icons/fi";
import type { Review } from "@/lib/types";

// Fixed extension ID — same for everyone (generated from key in manifest.json)
const EXTENSION_ID = "aefcojnlbcfejombefamnjfhnadjgcla";

export default function PortalLoginLink({ review, className }: { review: Review; className?: string }) {
  if (review.portal_username && review.portal_password) {
    const params = new URLSearchParams({
      platform: review.platform === "UberEats" ? "UBEREATS" : "DOORDASH",
      username: review.portal_username,
      password: review.portal_password,
      store_id: review.store_id || "",
      review_url: review.portal_link || "",
    });

    return (
      <a
        href={`chrome-extension://${EXTENSION_ID}/login_redirect.html?${params.toString()}`}
        target="_blank"
        className={className || "text-[#FF4B4B] hover:text-[#E04343] flex items-center gap-1 text-xs font-medium"}
      >
        <FiExternalLink size={13} />
        Login to Portal
      </a>
    );
  }

  if (review.portal_link) {
    return (
      <a
        href={review.portal_link}
        target="_blank"
        rel="noopener noreferrer"
        className={className || "text-blue-400 hover:text-blue-300 flex items-center gap-1 text-xs"}
      >
        <FiExternalLink size={13} />
        Portal
      </a>
    );
  }

  return <span className="text-gray-600">-</span>;
}
