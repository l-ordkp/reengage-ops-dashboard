/**
 * Content Script — DoorDash & UberEats Merchant Portals
 * Detects the review reply area, fetches the AI-generated response
 * from the ReEngage API, and injects full context + action buttons.
 */

(function () {
  "use strict";

  // ── Platform detection ──
  const platform = window.location.hostname.includes("ubereats") ? "ubereats" : "doordash";
  const UBEREATS_REVIEW_RE = /\/feedback\/reviews\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;

  let currentDeliveryUuid = null;
  let injectedForUuid = null; // prevent duplicate injection
  let operatorEmail = "";
  let injectInProgress = false; // prevent concurrent API calls
  let currentReviewData = null; // ReEngage response data for the current review
  const autoMarkedOrders = new Set(); // prevent duplicate auto-marks

  // ── Listen for platform response confirmations (from interceptor.js in MAIN world) ──
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;

    // Case 1: Reply was just submitted by the operator
    if (event.data?.type === "REENGAGE_REPLY_SUBMITTED") {
      if (!currentDeliveryUuid || !currentReviewData || autoMarkedOrders.has(currentDeliveryUuid)) return;
      console.log(`[ReEngage] Reply submitted on ${event.data.platform} — auto-marking ${currentDeliveryUuid}`);
      autoMarkedOrders.add(currentDeliveryUuid);
      const platformName = event.data.platform === "ubereats" ? "UberEats" : "Doordash";

      // QC: compare what operator posted vs what AI generated
      const qc = event.data.qc || {};
      const aiResponse = currentReviewData.response_text || "";
      const aiCoupon = currentReviewData.coupon_value ? String(currentReviewData.coupon_value) : "0";
      const repliedResponse = qc.replied_response || "";
      const repliedDiscount = qc.replied_discount || "NONE";

      const exactMatchResponse = repliedResponse.trim() === aiResponse.trim();
      // Discount match: check if coupon was applied when expected (or not applied when not expected)
      // UberEats uses tier names (NONE, TIER_1, TIER_2, etc.) not dollar amounts
      const couponExpected = aiCoupon !== "0" && aiCoupon !== "0.0";
      const couponApplied = repliedDiscount !== "NONE" && repliedDiscount !== "" && repliedDiscount !== "0";
      const exactMatchDiscount = couponExpected === couponApplied;

      console.log(`[ReEngage QC] Response match: ${exactMatchResponse}, Discount match: ${exactMatchDiscount}`);
      console.log(`[ReEngage QC] Replied: "${repliedResponse.slice(0, 50)}..." | AI: "${aiResponse.slice(0, 50)}..."`);
      console.log(`[ReEngage QC] Replied discount: ${repliedDiscount} | AI coupon: ${aiCoupon}`);

      chrome.runtime.sendMessage({
        type: "MARK_RESPONDED",
        orderId: currentDeliveryUuid,
        platform: platformName,
        chainName: currentReviewData.slug || "",
        qc: {
          replied_response: repliedResponse,
          replied_discount: repliedDiscount,
          exact_match_response: exactMatchResponse,
          exact_match_discount: exactMatchDiscount,
          platform_reply_id: qc.platform_reply_id || "",
          platform_coupon_id: qc.platform_coupon_id || "",
        }
      }, (result) => {
        if (result && result.success) {
          const matchIcon = exactMatchResponse ? "✅" : "⚠️";
          console.log(`[ReEngage] Auto-marked ${currentDeliveryUuid} as responded ${matchIcon}`);
          showToast(exactMatchResponse ? "Response verified and logged! ✅" : "Response logged — text mismatch detected ⚠️");
        } else {
          console.warn(`[ReEngage] Auto-mark failed:`, result?.error);
        }
      });
      return;
    }

    // Case 2: Reviews list re-fetched with responded reviews.
    //
    // Used to be scoped to "did the currently-open review get a reply?". We
    // now process the entire batch: any review the platform reports as
    // replied gets back-marked, even ones the operator never opened. This
    // shuts the loop where ELT lag re-assigns reviews the merchant has
    // already solved on the platform. Dedup is persisted in
    // chrome.storage.local so refreshes/tabs don't re-send the same UUIDs.
    if (event.data?.type !== "REENGAGE_PLATFORM_RESPONDED") return;

    const { platform: respPlatform, responded } = event.data;
    if (!Array.isArray(responded) || responded.length === 0) return;

    console.log(`[ReEngage] Intercepted ${responded.length} responded reviews from ${respPlatform}`);

    // Build (review_uid, order_id) pairs aligned with how the dashboard
    // derives review_uid: DD = cxReviewId, UE = workflowUUID (review_id NULL).
    const candidates = [];
    for (const r of responded) {
      if (respPlatform === "doordash") {
        const orderId = r.deliveryUuid || null;
        const reviewUid = r.cxReviewId || orderId;
        if (orderId && reviewUid) {
          candidates.push({
            platform: "Doordash",
            review_uid: reviewUid,
            order_id: orderId,
            store_id: r.storeId ? String(r.storeId) : "",
          });
        }
      } else if (respPlatform === "ubereats") {
        const uuid = r.workflowUUID || null;
        if (uuid) {
          candidates.push({
            platform: "UberEats",
            review_uid: uuid,
            order_id: uuid,
            store_id: r.storeId ? String(r.storeId) : "",
          });
        }
      }
    }
    if (candidates.length === 0) return;

    chrome.storage.local.get("observed_seen", (data) => {
      const seen = data.observed_seen || {};
      const toSend = [];
      for (const c of candidates) {
        if (seen[c.review_uid] || autoMarkedOrders.has(c.review_uid) || autoMarkedOrders.has(c.order_id)) continue;
        toSend.push(c);
        seen[c.review_uid] = true;
      }
      if (toSend.length === 0) return;

      chrome.runtime.sendMessage({ type: "OBSERVED_RESPONDED", items: toSend }, (result) => {
        if (result && result.success) {
          // Persist dedup ONLY after the backend confirms it processed the batch
          // (a failed request shouldn't burn the UUIDs — we'd want to retry on
          // the next list refresh).
          chrome.storage.local.set({ observed_seen: seen });
          for (const item of toSend) autoMarkedOrders.add(item.review_uid);
          const summary = result.data || {};
          console.log(
            `[ReEngage] observed-responded: sent=${toSend.length} ` +
            `inserted=${summary.inserted || 0} flipped=${summary.flipped || 0} ` +
            `skipped=${summary.skipped || 0}`
          );
          // If the operator's current review was in the batch and actually
          // changed state (insert or flip), surface a toast so they know
          // "this one's already done."
          if (currentDeliveryUuid && toSend.some(i => i.review_uid === currentDeliveryUuid || i.order_id === currentDeliveryUuid)) {
            if ((summary.inserted || 0) + (summary.flipped || 0) > 0) {
              showToast("Already replied on the platform — marked complete.");
            }
          }
        } else {
          console.warn(`[ReEngage] observed-responded failed:`, result?.error);
        }
      });
    });
  });

  // Auto-detect operator email from Chrome profile
  chrome.runtime.sendMessage({ type: "GET_OPERATOR_EMAIL" }, (email) => {
    operatorEmail = email || "";
  });

  // Listen for delivery_uuid / workflowUUID from background script
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "DELIVERY_UUID_CAPTURED") {
      currentDeliveryUuid = message.delivery_uuid;
      console.log(`[ReEngage] Got UUID (${platform}):`, currentDeliveryUuid);
      tryInject();
    }
  });

  // ── UberEats: Also extract UUID from URL on load ──
  if (platform === "ubereats") {
    const match = window.location.pathname.match(UBEREATS_REVIEW_RE);
    if (match) {
      currentDeliveryUuid = match[1];
      console.log("[ReEngage] Got UberEats UUID from URL:", currentDeliveryUuid);
    }
  }

  // ── Platform-specific selectors ──
  function findTextarea() {
    if (platform === "doordash") {
      return document.querySelector('textarea[data-anchor-id="ComplaintResponseComposeBox"]');
    }
    // UberEats: textarea with "Reply privately to" placeholder
    const textareas = document.querySelectorAll("textarea");
    for (const ta of textareas) {
      if (ta.placeholder && ta.placeholder.startsWith("Reply privately to")) {
        return ta;
      }
    }
    return null;
  }

  function isSidesheetNode(node) {
    if (!node.querySelector) return false;
    if (platform === "doordash") {
      return (
        node.querySelector('[data-anchor-id="ComplaintResponse"]') ||
        node.querySelector('[data-anchor-id="ComplaintResponseComposeBox"]') ||
        (node.matches && node.matches('[data-anchor-id="ComplaintResponse"]'))
      );
    }
    // UberEats: detect review detail panel
    return !!(node.querySelector('textarea[placeholder^="Reply privately to"]'));
  }

  function getTextareaWrapper(textarea) {
    if (platform === "doordash") {
      return (
        textarea.closest(".StyledStackChildren-sc-1cimee4-0") ||
        textarea.closest(".FieldRoot-sc-13e9y4-0") ||
        textarea.parentElement
      );
    }
    // UberEats: walk up to find a suitable container
    return textarea.closest("form") || textarea.parentElement;
  }

  // ── MutationObserver: watch for sidesheet open + textarea appearing ──
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (isSidesheetNode(node)) {
          console.log("[ReEngage] Sidesheet detected");
          setTimeout(tryInject, 300);
          return; // only trigger once per batch
        }
      }
    }

    // UberEats: also check if textarea appeared via subtree changes
    if (platform === "ubereats" && currentDeliveryUuid && injectedForUuid !== currentDeliveryUuid) {
      const textarea = findTextarea();
      if (textarea) {
        setTimeout(tryInject, 300);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // UberEats: Try injection on initial load (page might already have the review open)
  if (platform === "ubereats") {
    setTimeout(tryInject, 1000);
  }

  // ── Core injection logic ──
  async function tryInject() {
    if (injectInProgress) return;

    const textarea = findTextarea();
    if (!textarea) return;

    // Don't re-inject for the same UUID
    if (injectedForUuid === currentDeliveryUuid && document.querySelector(".reengage-btn-container")) {
      return;
    }

    injectInProgress = true;
    try {
      // If we don't have a UUID yet, try to get it from storage
      if (!currentDeliveryUuid) {
        const data = await new Promise((resolve) => {
          chrome.runtime.sendMessage({ type: "GET_DELIVERY_UUID" }, resolve);
        });
        if (data && data.delivery_uuid) {
          currentDeliveryUuid = data.delivery_uuid;
        }
      }

      // UberEats: also try to extract from current URL
      if (!currentDeliveryUuid && platform === "ubereats") {
        const match = window.location.pathname.match(UBEREATS_REVIEW_RE);
        if (match) {
          currentDeliveryUuid = match[1];
        }
      }

      if (!currentDeliveryUuid) {
        injectStatusBadge(textarea, "waiting", "Waiting for order ID...");
        return;
      }

      // Get operator email (auto-detected from Chrome profile via background)
      if (!operatorEmail) {
        operatorEmail = await new Promise((resolve) => {
          chrome.runtime.sendMessage({ type: "GET_OPERATOR_EMAIL" }, resolve);
        }) || "";
      }

      if (!operatorEmail) {
        injectStatusBadge(textarea, "error", "Not signed into Chrome. Sign in with your loopai.com account.");
        return;
      }

      // Remove any existing injection
      removeExistingInjection();

      // Fetch response via background script (avoids page CSP restrictions)
      injectStatusBadge(textarea, "loading", "Fetching response...");

      const result = await new Promise((resolve) => {
        chrome.runtime.sendMessage({
          type: "FETCH_RESPONSE",
          orderId: currentDeliveryUuid
        }, resolve);
      });

      if (!result || !result.success) {
        throw new Error(result ? result.error : "No response from background");
      }
      const data = result.data;

      removeExistingInjection();

      if (!data.found || !data.response_text) {
        injectStatusBadge(textarea, "empty", "No response found for this order.");
        return;
      }

      currentReviewData = data; // track for auto-detection
      injectResponsePanel(textarea, data);
      injectedForUuid = currentDeliveryUuid;
    } catch (err) {
      removeExistingInjection();
      injectStatusBadge(textarea, "error", `API error: ${err.message}`);
    } finally {
      injectInProgress = false;
    }
  }

  // ── Inject full context panel + action buttons ──
  function injectResponsePanel(textarea, data) {
    const container = document.createElement("div");
    container.className = "reengage-btn-container";

    // Already-responded warning
    const alreadyResponded = data.response_sent || data.is_replied;
    if (alreadyResponded) {
      const warning = document.createElement("div");
      warning.className = "reengage-already-responded";
      const respondedDate = data.response_sent
        ? new Date(data.response_sent).toLocaleDateString()
        : "previously";
      warning.innerHTML = `<strong>Already responded</strong> (${respondedDate}). Posting again will create a duplicate reply.`;
      container.appendChild(warning);
    }

    // Review context section
    const context = document.createElement("div");
    context.className = "reengage-context";

    // Customer name + rating
    const header = document.createElement("div");
    header.className = "reengage-context-header";
    const customerName = data.customer_name || "Unknown";
    const starRating = data.star_rating;
    const stars = starRating ? renderStars(parseInt(starRating)) : "";
    header.innerHTML = `<span class="reengage-customer-name">${escapeHtml(customerName)}</span>${stars ? ` <span class="reengage-stars">${stars}</span>` : ""}`;
    context.appendChild(header);

    // Original review text (collapsible)
    if (data.review_text) {
      const reviewBlock = document.createElement("div");
      reviewBlock.className = "reengage-review-text";
      reviewBlock.textContent = data.review_text;
      context.appendChild(reviewBlock);
    }

    container.appendChild(context);

    // Full AI response (not truncated)
    const responseBlock = document.createElement("div");
    responseBlock.className = "reengage-preview";
    responseBlock.textContent = data.response_text;
    container.appendChild(responseBlock);

    // Coupon instruction
    if (data.coupon_value && data.coupon_value > 0) {
      const couponBadge = document.createElement("div");
      couponBadge.className = "reengage-coupon-badge";
      couponBadge.innerHTML = `<strong>Apply $${data.coupon_value} discount</strong> before submitting the reply`;
      container.appendChild(couponBadge);
    }

    // Button row
    const btnRow = document.createElement("div");
    btnRow.className = "reengage-btn-row";

    // Copy button
    const copyBtn = document.createElement("button");
    copyBtn.className = "reengage-copy-btn";
    copyBtn.textContent = "Copy Response";
    copyBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(data.response_text);
        showToast("Response copied to clipboard!");
        copyBtn.textContent = "Copied!";
        copyBtn.classList.add("reengage-copied");
        setTimeout(() => {
          copyBtn.textContent = "Copy Response";
          copyBtn.classList.remove("reengage-copied");
        }, 2000);
      } catch (err) {
        showToast("Clipboard failed - please copy manually from the text above");
      }
    });
    btnRow.appendChild(copyBtn);

    container.appendChild(btnRow);

    // Source badge + operator badge
    const footerRow = document.createElement("div");
    footerRow.className = "reengage-footer-row";

    const sourceBadge = document.createElement("span");
    sourceBadge.className = "reengage-source-badge";
    sourceBadge.textContent = `ReEngage ${data.response_type === "ai" ? "AI" : "Template"} Response`;
    footerRow.appendChild(sourceBadge);

    if (operatorEmail) {
      const opBadge = document.createElement("span");
      opBadge.className = "reengage-operator-badge";
      opBadge.textContent = operatorEmail;
      footerRow.appendChild(opBadge);
    }

    container.appendChild(footerRow);

    // Insert before the textarea's wrapper
    const textareaWrapper = getTextareaWrapper(textarea);
    textareaWrapper.parentElement.insertBefore(container, textareaWrapper);
  }

  // ── Helpers ──
  function renderStars(count) {
    if (!count || count < 1 || count > 5) return "";
    return "★".repeat(count) + "☆".repeat(5 - count);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Status badge (loading, error, etc.) ──
  function injectStatusBadge(textarea, type, message) {
    removeExistingInjection();
    const badge = document.createElement("div");
    badge.className = `reengage-btn-container reengage-status-${type}`;
    badge.textContent = message;

    const textareaWrapper = getTextareaWrapper(textarea);
    textareaWrapper.parentElement.insertBefore(badge, textareaWrapper);
  }

  function removeExistingInjection() {
    document.querySelectorAll(".reengage-btn-container").forEach((el) => el.remove());
  }

  // ── Toast notification ──
  function showToast(message) {
    const existing = document.querySelector(".reengage-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "reengage-toast";
    toast.textContent = message;
    document.body.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("reengage-toast-visible"));

    setTimeout(() => {
      toast.classList.remove("reengage-toast-visible");
      setTimeout(() => toast.remove(), 300);
    }, 2500);
  }

  // ── Reset on sidesheet close ──
  const closeObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.removedNodes) {
        if (node.nodeType !== 1) continue;
        if (!node.querySelector) continue;
        const isClosing = platform === "doordash"
          ? (node.querySelector('[data-anchor-id="ComplaintResponse"]') ||
             (node.matches && node.matches('[data-anchor-id="ComplaintResponse"]')))
          : !!(node.querySelector('textarea[placeholder^="Reply privately to"]'));

        if (isClosing) {
          // UberEats: only reset if we're not already on a new review URL
          if (platform === "ubereats") {
            const stillOnReview = window.location.pathname.match(UBEREATS_REVIEW_RE);
            if (stillOnReview) continue; // navigated to a different review, don't reset
          }
          currentDeliveryUuid = null;
          injectedForUuid = null;
          currentReviewData = null;
        }
      }
    }
  });
  closeObserver.observe(document.body, { childList: true, subtree: true });

  // ── UberEats: Watch for URL changes (SPA navigation between reviews) ──
  if (platform === "ubereats") {
    let lastUrl = window.location.href;
    const urlObserver = new MutationObserver(() => {
      if (window.location.href !== lastUrl) {
        lastUrl = window.location.href;
        const match = window.location.pathname.match(UBEREATS_REVIEW_RE);
        if (match) {
          currentDeliveryUuid = match[1];
          injectedForUuid = null;
          currentReviewData = null;
          removeExistingInjection();
          console.log("[ReEngage] UberEats URL changed, new UUID:", currentDeliveryUuid);
          setTimeout(tryInject, 500);
        } else {
          // Navigated away from a review
          currentDeliveryUuid = null;
          injectedForUuid = null;
          currentReviewData = null;
          removeExistingInjection();
        }
      }
    });
    urlObserver.observe(document.body, { childList: true, subtree: true });
  }
})();
