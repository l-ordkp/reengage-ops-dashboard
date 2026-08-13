/**
 * Background Service Worker
 * Intercepts Segment analytics POSTs to extract delivery_uuid from DoorDash events.
 * Parses UberEats review page URLs to extract workflowUUID.
 * Proxies API calls to the ReEngage Cloud Run backend.
 */

// Build tag — printed on service-worker startup so you can confirm which code
// is actually running (chrome://extensions → "service worker" → Console).
const BG_BUILD = "throttle-v2 (2.2.5)";
console.log(`[ReEngage BG] build: ${BG_BUILD}`);

// Default API base — can be overridden in popup for local/ngrok testing
const DEFAULT_API_BASE = "https://reengage-ops-dashboard-v2-ul5ne76yva-uc.a.run.app";

// ── assignment-table write throttle ───────────────────────────────────────
// BigQuery serializes DML on the assignments table, so firing several writes
// in parallel collides ("Could not serialize access … concurrent update"),
// retries, and blows the nginx /api/extension/ timeout (proxy_read_timeout =
// 30s) — surfacing as 504s and dropped writes. BOTH mark-responded AND
// observed-responded write to that table, so we push them through ONE shared
// queue: strictly one write at a time, with a small gap, so they never collide
// with each other. This paces only the extension's background reporting; the
// operator keeps replying on the platform at full speed.
let _writeChain = Promise.resolve();
const WRITE_GAP_MS = 150;

function enqueueWrite(task) {
  // task: () => Promise<any>. Runs after all previously-queued writes finish,
  // then a short gap. Returns a promise resolving to task()'s result. A failed
  // task never breaks the chain (the next write still runs).
  const run = _writeChain.then(task);
  _writeChain = run.catch(() => {}).then(() => new Promise((r) => setTimeout(r, WRITE_GAP_MS)));
  return run;
}

// The observed-responded dedup ledger lives in chrome.storage.local (keyed
// "observed_seen") so content scripts can read/write it without the access-
// level dance that chrome.storage.session requires. Storage cost is trivial
// (~40 bytes per UUID), and the backend's three-state logic is idempotent
// against any re-sends if the dedup is ever wrong.

// ── Login Automation: Platform configs ──
const LOGIN_PLATFORM_CONFIG = {
  UBEREATS: {
    origins: ["https://ubereats.com", "https://uber.com", "https://merchants.ubereats.com", "https://auth.uber.com"],
    loginUrl: "https://merchants.ubereats.com/manager/"
  },
  DOORDASH: {
    origins: ["https://doordash.com", "https://www.doordash.com", "https://identity.doordash.com"],
    loginUrl: "https://www.doordash.com/merchant"
  }
};

// ── Login Automation: Intercept debug URL redirect ──
chrome.declarativeNetRequest.onRuleMatchedDebug.addListener((e) => {
  try {
    const url = e.request.url;
    const urlParams = new URLSearchParams(url.split("?")[1]);
    const username = (urlParams.get("username") || "").replace(/ /g, "+");
    const password = urlParams.get("password") || "";
    const platform = urlParams.get("platform") || "";
    const storeId = urlParams.get("store_id") || "";

    const config = LOGIN_PLATFORM_CONFIG[platform];
    if (!config) return;

    console.log(`[ReEngage Login] Intercepted login request for ${platform}`);

    // Build login URL with store redirect for UberEats
    let loginUrl = config.loginUrl;
    if (platform === "UBEREATS" && storeId) {
      const nextUrl = encodeURIComponent(`https://merchants.ubereats.com/manager/home/${storeId}`);
      loginUrl = `https://merchants.ubereats.com/manager/?next_url=${nextUrl}`;
    }

    // Clear cookies/cache for this platform, then navigate to login page
    chrome.browsingData.remove({ origins: config.origins }, {
      cacheStorage: true,
      cookies: true,
      localStorage: true,
      indexedDB: true,
      webSQL: true
    }, () => {
      // Store credentials for login.js to pick up
      chrome.storage.local.set({
        login_username: username,
        login_password: password,
        login_platform: platform,
        login_store_id: storeId,
      }, () => {
        chrome.tabs.update(e.tabId, { url: loginUrl });
      });
    });
  } catch (err) {
    console.error("[ReEngage Login] Error:", err);
  }
});

// ── DoorDash: Listen for Segment tracking calls ──
chrome.webRequest.onBeforeRequest.addListener(
  handleSegmentRequest,
  {
    urls: [
      "*://api.segment.io/v1/track*",
      "*://api.segment.com/v1/track*",
      "*://api.segment.io/v1/t*",
      "*://api.segment.com/v1/t*"
    ]
  },
  ["requestBody"]
);

function handleSegmentRequest(details) {
  if (details.method !== "POST" || !details.requestBody) return;

  const raw = details.requestBody.raw;
  if (!raw || raw.length === 0) return;

  try {
    const decoder = new TextDecoder("utf-8");
    const bodyText = raw.map(part => decoder.decode(part.bytes)).join("");
    const payload = JSON.parse(bodyText);

    const events = payload.batch || [payload];

    for (const event of events) {
      const props = event.properties || {};
      const deliveryUuid = props.delivery_uuid || props.deliveryUuid || props.order_uuid;

      if (deliveryUuid) {
        console.log("[ReEngage] Captured delivery_uuid:", deliveryUuid, "from event:", event.event);
        storeAndNotify(details.tabId, deliveryUuid, event.event || "unknown", {
          store_id: props.store_id || props.storeId || null,
          consumer_name: props.consumer_name || null
        });
      }
    }
  } catch (e) {
    // Silently ignore parse errors
  }
}

// ── Inject fetch interceptor into MAIN world on merchant portals ──
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId !== 0) return;
  chrome.scripting.executeScript({
    target: { tabId: details.tabId },
    files: ["interceptor.js"],
    world: "MAIN",
    injectImmediately: true
  }).catch(() => {});
}, {
  url: [
    { hostContains: "doordash.com" },
    { hostContains: "ubereats.com" }
  ]
});

// ── UberEats: Listen for review page navigation ──
chrome.webNavigation.onCompleted.addListener((details) => {
  try {
    const url = new URL(details.url);
    const match = url.pathname.match(/\/feedback\/reviews\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    if (match) {
      const workflowUUID = match[1];
      console.log("[ReEngage] Captured UberEats workflowUUID:", workflowUUID);
      storeAndNotify(details.tabId, workflowUUID, "ubereats_review_page", {});
    }
  } catch (e) {}
}, { url: [{ hostContains: "merchants.ubereats.com" }] });

chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.frameId !== 0) return;
  try {
    const url = new URL(details.url);
    const match = url.pathname.match(/\/feedback\/reviews\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    if (match) {
      const workflowUUID = match[1];
      console.log("[ReEngage] Captured UberEats workflowUUID (SPA nav):", workflowUUID);
      storeAndNotify(details.tabId, workflowUUID, "ubereats_review_page_spa", {});
    }
  } catch (e) {}
}, { url: [{ hostContains: "merchants.ubereats.com" }] });

// ── Shared: Store UUID and notify content script ──
function storeAndNotify(tabId, uuid, eventName, extra) {
  if (tabId <= 0) return;

  const storageKey = `tab_${tabId}`;
  const data = {
    delivery_uuid: uuid,
    timestamp: Date.now(),
    event_name: eventName,
    store_id: extra.store_id || null,
    consumer_name: extra.consumer_name || null
  };

  chrome.storage.session.set({ [storageKey]: data });

  chrome.tabs.sendMessage(tabId, {
    type: "DELIVERY_UUID_CAPTURED",
    ...data
  }).catch(() => {});
}

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab_${tabId}`);
});

// ── Get operator email — display only; API auth uses the operator token ──
function getOperatorEmail() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["operatorEmail", "emailVerified"], (result) => {
      if (result.operatorEmail && result.emailVerified) {
        resolve(result.operatorEmail);
      } else {
        resolve("");
      }
    });
  });
}

// ── Get operator token — backend-issued JWT from the popup's sign-in flow ──
function getOperatorToken() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["operatorToken", "emailVerified"], (result) => {
      if (result.operatorToken && result.emailVerified) {
        resolve(result.operatorToken);
      } else {
        resolve("");
      }
    });
  });
}

// ── Get API base URL (allows override for ngrok testing) ──
function getApiBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get("apiBase", (result) => {
      resolve(result.apiBase || DEFAULT_API_BASE);
    });
  });
}

// ── Message handler ──
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Login trigger from login_trigger.js on extension page
  if (message.type === "TRIGGER_LOGIN") {
    const { platform, username, password, storeId, reviewUrl } = message;
    console.log(`[ReEngage BG] TRIGGER_LOGIN received. platform=${platform}, username=${username ? "***" : "EMPTY"}, storeId=${storeId}, reviewUrl=${reviewUrl}`);
    console.log(`[ReEngage BG] sender.tab=`, sender.tab ? `tabId=${sender.tab.id}, url=${sender.tab.url}` : "NO TAB");

    const config = LOGIN_PLATFORM_CONFIG[platform];
    if (!config) {
      console.error(`[ReEngage BG] Unknown platform: ${platform}`);
      sendResponse({ ok: false, error: "Unknown platform" });
      return;
    }

    let loginUrl = config.loginUrl;
    if (platform === "UBEREATS") {
      const afterLogin = reviewUrl || (storeId ? `https://merchants.ubereats.com/manager/home/${storeId}/feedback/reviews` : "");
      if (afterLogin) {
        loginUrl = `https://merchants.ubereats.com/manager/?next_url=${encodeURIComponent(afterLogin)}`;
      }
    } else if (platform === "DOORDASH") {
      // DoorDash doesn't support next_url, but we store the review URL for later redirect
      if (reviewUrl) {
        chrome.storage.local.set({ login_redirect_after: reviewUrl });
      }
    }
    console.log(`[ReEngage BG] loginUrl=${loginUrl}`);

    // Smart check: if same account AND platform cookies still exist, skip re-login
    const cookieDomains = platform === "UBEREATS"
      ? [".ubereats.com", ".uber.com", "merchants.ubereats.com"]
      : [".doordash.com", "www.doordash.com"];

    chrome.storage.local.get(["login_last_username", "login_last_platform"], (prev) => {
      const sameAccount = prev.login_last_username === username && prev.login_last_platform === platform;

      if (!sameAccount || !reviewUrl) {
        doFullLogin();
        return;
      }

      // Same account — check if session cookies still exist across all platform domains
      Promise.all(cookieDomains.map(d => new Promise(resolve => {
        chrome.cookies.getAll({ domain: d }, (c) => resolve(c ? c.length : 0));
      }))).then((counts) => {
        const totalCookies = counts.reduce((a, b) => a + b, 0);
        const hasSession = totalCookies > 10; // UberEats sets 20+ cookies when properly logged in
        console.log(`[ReEngage BG] Same account. Cookies: ${counts.join("+")}=${totalCookies}. hasSession=${hasSession}`);

        if (hasSession) {
          console.log(`[ReEngage BG] Session alive — going directly to review.`);
          if (sender.tab) {
            chrome.tabs.update(sender.tab.id, { url: reviewUrl }, () => {
              sendResponse({ ok: true, loginUrl: reviewUrl, skippedLogin: true });
            });
          } else {
            chrome.tabs.create({ url: reviewUrl }, () => {
              sendResponse({ ok: true, loginUrl: reviewUrl, skippedLogin: true, newTab: true });
            });
          }
        } else {
          console.log(`[ReEngage BG] Session expired — doing full login.`);
          doFullLogin();
        }
      });
      return;

      function doFullLogin() {
        console.log(`[ReEngage BG] Full login — clearing cookies`);
        chrome.browsingData.remove({ origins: config.origins }, {
          cacheStorage: true,
          cookies: true,
          localStorage: true,
          indexedDB: true,
          webSQL: true
        }, () => {
          if (chrome.runtime.lastError) {
            console.error(`[ReEngage BG] browsingData.remove error:`, chrome.runtime.lastError.message);
          }
          console.log(`[ReEngage BG] Cookies cleared. Storing credentials...`);
          chrome.storage.local.set({
            login_username: username,
            login_password: password,
            login_platform: platform,
            login_store_id: storeId,
            login_last_username: username,
            login_last_platform: platform,
          }, () => {
            console.log(`[ReEngage BG] Credentials stored. Redirecting tab...`);
            if (sender.tab) {
              chrome.tabs.update(sender.tab.id, { url: loginUrl }, () => {
                console.log(`[ReEngage BG] Tab redirected to ${loginUrl}`);
                sendResponse({ ok: true, loginUrl });
              });
            } else {
              chrome.tabs.create({ url: loginUrl }, () => {
                sendResponse({ ok: true, loginUrl, newTab: true });
              });
            }
          });
        });
      }
    });
    return true; // async response
  }

  if (message.type === "GET_DELIVERY_UUID" && sender.tab) {
    const storageKey = `tab_${sender.tab.id}`;
    chrome.storage.session.get(storageKey, (result) => {
      sendResponse(result[storageKey] || null);
    });
    return true;
  }

  if (message.type === "GET_OPERATOR_EMAIL") {
    getOperatorEmail().then(sendResponse);
    return true;
  }

  if (message.type === "GET_API_BASE") {
    getApiBase().then(sendResponse);
    return true;
  }

  // Relay OTP fetches from login.js content scripts. Content-script fetches
  // carry the merchant portal's Origin (identity.doordash.com / auth.uber.com),
  // which the backend's CORS allowlist rejects since the Jul 2026 Scrut VAPT
  // fix (backend PR #16726). Background-worker fetches use the extension's
  // host_permissions and are exempt from CORS entirely.
  if (message.type === "FETCH_OTP") {
    const { url } = message;
    let parsedUrl;
    try { parsedUrl = new URL(url); } catch (e) { parsedUrl = null; }
    if (!parsedUrl || parsedUrl.protocol !== "https:" || parsedUrl.hostname !== "internal.loopapplication.xyz") {
      sendResponse({ success: false, error: "FETCH_OTP url or protocol not allowed" });
      return true;
    }
    fetch(parsedUrl.href)
      .then(resp => resp.text().then(text => ({ ok: resp.ok, status: resp.status, text })))
      .then(({ ok, status, text }) => {
        if (!ok) {
          sendResponse({ success: false, error: `HTTP ${status}: ${text.slice(0, 200)}` });
        } else {
          sendResponse({ success: true, text });
        }
      })
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }

  // Lookup AI response from Cloud Run
  if (message.type === "FETCH_RESPONSE") {
    const { orderId } = message;
    Promise.all([getApiBase(), getOperatorToken()]).then(([apiBase, token]) => {
      const url = `${apiBase}/api/extension/lookup?order_id=${encodeURIComponent(orderId)}`;
      fetch(url, {
        headers: {
          "Authorization": `Bearer ${token}`,
          "ngrok-skip-browser-warning": "true"
        }
      })
        .then(resp => resp.json().then(data => ({ ok: resp.ok, status: resp.status, data })))
        .then(({ ok, status, data }) => {
          if (!ok) {
            sendResponse({ success: false, error: data.detail || `HTTP ${status}` });
          } else {
            sendResponse({ success: true, data });
          }
        })
        .catch(err => sendResponse({ success: false, error: err.message }));
    });
    return true;
  }

  // Bulk back-mark reviews the platform itself reports as already replied.
  // Different endpoint from MARK_RESPONDED — never carries QC, never overwrites
  // a real submit's metadata on the backend.
  if (message.type === "OBSERVED_RESPONDED") {
    const { items } = message;
    if (!Array.isArray(items) || items.length === 0) {
      sendResponse({ success: true, data: { processed: 0 } });
      return true;
    }
    enqueueWrite(() => Promise.all([getApiBase(), getOperatorToken()]).then(([apiBase, token]) =>
      fetch(`${apiBase}/api/extension/observed-responded`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify({ items })
      })
        .then(resp => resp.json().then(data => ({ ok: resp.ok, status: resp.status, data })))
        .then(({ ok, status, data }) => {
          if (!ok) throw new Error(data.detail || `HTTP ${status}`);
          console.log(`[ReEngage BG] observed-responded: ${JSON.stringify(data)}`);
          return data;
        })
    ))
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }

  // Mark responded on Cloud Run — THROTTLED via enqueueWrite(): shares the one
  // assignment-table write queue with observed-responded, so writes go
  // one-at-a-time and never collide on BigQuery's serialized DML. Only paces
  // background reporting; the operator is unaffected.
  if (message.type === "MARK_RESPONDED") {
    const { orderId, platform, chainName, qc } = message;
    enqueueWrite(() => Promise.all([getApiBase(), getOperatorToken()]).then(([apiBase, token]) => {
      const body = {
        order_id: orderId,
        platform: platform,
        chain_name: chainName || ""
      };
      // Include QC data if available
      if (qc) {
        body.replied_response = qc.replied_response || "";
        body.replied_discount = qc.replied_discount || "";
        body.exact_match_response = qc.exact_match_response || false;
        body.exact_match_discount = qc.exact_match_discount || false;
        body.platform_reply_id = qc.platform_reply_id || "";
        body.platform_coupon_id = qc.platform_coupon_id || "";
      }
      console.log(`[ReEngage BG] MARK_RESPONDED with QC:`, qc ? `match_resp=${qc.exact_match_response}, match_disc=${qc.exact_match_discount}` : "no QC data");
      return fetch(`${apiBase}/api/extension/mark-responded`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify(body)
      }).then(resp => resp.json());
    }))
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }
});
