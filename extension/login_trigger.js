/**
 * Login Trigger — Parses login credentials from URL params and sends to background.js.
 * Runs as a script on login_redirect.html (extension page).
 */

(function () {
  console.log("[ReEngage Login Trigger] Script loaded on:", window.location.href);

  const params = new URLSearchParams(window.location.search);
  const platform = params.get("platform");
  const username = (params.get("username") || "").replace(/ /g, "+");
  const password = params.get("password") || "";
  const storeId = params.get("store_id") || "";
  const reviewUrl = params.get("review_url") || "";

  console.log("[ReEngage Login Trigger] Parsed params:", { platform, username: username ? "***" : "EMPTY", password: password ? "***" : "EMPTY", storeId, reviewUrl });

  if (!platform || !username) {
    const msg = "Missing login parameters.";
    console.error("[ReEngage Login Trigger]", msg);
    document.body.textContent = msg;
    return;
  }

  document.body.textContent = `Logging into ${platform}... please wait`;

  console.log("[ReEngage Login Trigger] Sending TRIGGER_LOGIN to background.js");

  chrome.runtime.sendMessage({
    type: "TRIGGER_LOGIN",
    platform,
    username,
    password,
    storeId,
    reviewUrl,
  }, (response) => {
    if (chrome.runtime.lastError) {
      console.error("[ReEngage Login Trigger] Message failed:", chrome.runtime.lastError.message);
      document.body.textContent = `Error: ${chrome.runtime.lastError.message}`;
    } else {
      console.log("[ReEngage Login Trigger] Background responded:", response);
      document.body.textContent = `Redirecting to ${platform} login...`;
    }
  });
})();
