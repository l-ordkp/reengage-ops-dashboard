"use client";

import { useEffect, useState } from "react";
import { FiExternalLink } from "react-icons/fi";
import type { Review } from "@/lib/types";

// Extension IDs per team member (add new ones here until we publish on Chrome Web Store)
const EXTENSION_IDS = [
  "jkjmledlhnfnendfbkeppljnmdibhcgo",  // kshitij
  "nbgfeglkpdjockmdlilickeclbcpaode",  // rishi
];

function useExtensionId() {
  const [extId, setExtId] = useState(EXTENSION_IDS[0]);

  useEffect(() => {
    // Check which extension is installed by looking for the data attribute
    // injected by the extension's content script, or try fetching manifest
    const attr = document.documentElement.getAttribute("data-reengage-extension-id");
    if (attr) {
      setExtId(attr);
      return;
    }
    // Fallback: try each ID by fetching their manifest
    for (const id of EXTENSION_IDS) {
      const img = new Image();
      img.onload = () => setExtId(id);
      img.src = `chrome-extension://${id}/icon48.png`;
    }
  }, []);

  return extId;
}

export default function PortalLoginLink({ review, className }: { review: Review; className?: string }) {
  const extId = useExtensionId();

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
        href={`chrome-extension://${extId}/login_redirect.html?${params.toString()}`}
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
