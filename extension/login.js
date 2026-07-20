/**
 * Login Automation — Auto-fills merchant portal login forms.
 * Triggered when background.js stores credentials and navigates to the login page.
 * Credentials are read from chrome.storage.local and removed after use.
 */

const LOGIN_SELECTORS = {
  // UberEats
  UBER_USERNAME: "#PHONE_NUMBER_or_EMAIL_ADDRESS",
  UBER_NEXT_BUTTON: "button[id='forward-button']",
  UBER_OTP: "input[inputmode='numeric']",
  UBER_PASSWORD: "#PASSWORD",
  // DoorDash
  DOORDASH_USERNAME: "input[data-anchor-id='IdentityLoginPageEmailField']",
  DOORDASH_PASSWORD: "input[data-anchor-id='IdentityLoginPagePasswordField']",
  DOORDASH_MERCHANT_LOGIN_BUTTON: "#merchant-login-submit-button",
  DOORDASH_USE_PASSWORD_BUTTON: "#merchant-use-password-button",
  DOORDASH_LOGIN_BUTTON: "#login-submit-button",
  DOORDASH_OTP: "input[type='number']",
};

console.log(`[ReEngage Login] login.js loaded on ${window.location.hostname}${window.location.pathname}`);

chrome.storage.local.get(
  ["login_username", "login_password", "login_platform", "login_store_id"],
  async (data) => {
    const username = data.login_username;
    const password = data.login_password;
    const platform = data.login_platform;
    const storeId = data.login_store_id;

    console.log(`[ReEngage Login] Stored creds: platform=${platform || "NONE"}, username=${username ? "***" : "NONE"}, password=${password ? "***" : "NONE"}, storeId=${storeId || "NONE"}`);

    if (!platform || !username) {
      console.log("[ReEngage Login] No credentials stored — skipping");
      return;
    }

    const host = window.location.hostname;
    console.log(`[ReEngage Login] Auto-login for ${platform} on ${host}`);

    // Only attempt login on the correct login page
    // UberEats: auth.uber.com (not merchants.ubereats.com which redirects)
    // DoorDash: identity.doordash.com or www.doordash.com (login page)
    if (platform === "UBEREATS" && !host.includes("auth.uber.com")) {
      console.log("[ReEngage Login] Waiting for redirect to auth.uber.com...");
      return; // Keep credentials, login.js will run again on auth.uber.com
    }

    let success = false;
    try {
      switch (platform) {
        case "UBEREATS":
          console.log("[ReEngage Login] Starting UberEats login flow...");
          success = await loginUberEats(username, password, storeId);
          break;
        case "DOORDASH":
          console.log("[ReEngage Login] Starting DoorDash login flow...");
          success = await loginDoorDash(username, password, storeId);
          break;
      }
      console.log(`[ReEngage Login] Login flow completed. success=${success}`);
    } catch (e) {
      console.error("[ReEngage Login] Error during login:", e);
    }

    // Don't clear credentials here — only clear when we confirm
    // we're on the merchant portal (not still on auth page)
    const currentHost = window.location.hostname;
    const onMerchantPortal = currentHost.includes("merchants.ubereats.com") || currentHost.includes("merchants.doordash.com") || currentHost.includes("www.doordash.com");
    if (success && onMerchantPortal) {
      console.log("[ReEngage Login] On merchant portal — clearing stored credentials");
      chrome.storage.local.remove([
        "login_username",
        "login_password",
        "login_platform",
        "login_store_id",
      ]);
    } else {
      console.log(`[ReEngage Login] Keeping credentials (success=${success}, onPortal=${onMerchantPortal}, host=${currentHost})`);
    }
  }
);

// ── DoorDash Login ──
async function loginDoorDash(username, password, storeId) {
  console.log("[ReEngage Login] [DD] Waiting for page load...");
  await sleep(4000);

  // Step 1: Enter username
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_USERNAME)) {
    console.log("[ReEngage Login] [DD] Step 1: Entering username");
    await typeIntoField(LOGIN_SELECTORS.DOORDASH_USERNAME, username);
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_MERCHANT_LOGIN_BUTTON));
  } else {
    console.log("[ReEngage Login] [DD] Username field not found — redirecting");
    redirectIfNeeded(getDoorDashUrl(storeId), "https://www.doordash.com/merchant");
    return false;
  }

  await sleep(4000);

  // Step 2: Click "Use password" if shown
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_USE_PASSWORD_BUTTON)) {
    console.log("[ReEngage Login] [DD] Step 2: Clicking 'Use password'");
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_USE_PASSWORD_BUTTON));
    await sleep(4000);
  }

  // Step 3: Enter password
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_PASSWORD)) {
    console.log("[ReEngage Login] [DD] Step 3: Entering password");
    await typeIntoField(LOGIN_SELECTORS.DOORDASH_PASSWORD, password);
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_LOGIN_BUTTON));
  } else {
    console.log("[ReEngage Login] [DD] Step 3: Password field not found");
  }

  console.log("[ReEngage Login] [DD] Waiting for OTP screen (10s)...");
  await sleep(10000);

  // Step 4: Handle OTP if needed
  const otpField = document.querySelector(LOGIN_SELECTORS.DOORDASH_OTP);
  if (otpField) {
    console.log("[ReEngage Login] [DD] Step 4: OTP field found. Waiting for fresh OTP...");
    await sleep(5000);

    let ddOtpSuccess = false;
    for (let otpAttempt = 0; otpAttempt < 3 && !ddOtpSuccess; otpAttempt++) {
      try {
        let otp = await fetchOtp(
          `https://internal.loopapplication.xyz/get_last_otp?username=${encodeURIComponent(username)}`
        );
        otp = otp.replace(/"/g, "").trim();
        console.log(`[ReEngage Login] [DD] OTP attempt ${otpAttempt + 1}: "${otp}" (${otp.length} chars)`);

        if (!otp || otp.length < 4) {
          console.log("[ReEngage Login] [DD] OTP too short, retrying in 5s...");
          await sleep(5000);
          continue;
        }

        await typeIntoField(LOGIN_SELECTORS.DOORDASH_OTP, otp);
        simulateClick(document.querySelector("#prism-modal-footer > button:nth-child(2)"));
        await sleep(4000);
        console.log("[ReEngage Login] [DD] OTP submitted");

        // Check if still on OTP screen
        if (document.querySelector(LOGIN_SELECTORS.DOORDASH_OTP)) {
          console.log("[ReEngage Login] [DD] OTP might be wrong, retrying in 5s...");
          await sleep(5000);
        } else {
          ddOtpSuccess = true;
        }
      } catch (e) {
        console.error(`[ReEngage Login] [DD] OTP attempt ${otpAttempt + 1} failed:`, e);
        await sleep(5000);
      }
    }
  } else {
    console.log("[ReEngage Login] [DD] Step 4: No OTP field — login may have completed");
  }
  return true;
}

// ── UberEats Login ──
async function loginUberEats(username, password, storeId) {
  await sleep(4000);

  // Step 1: Enter username
  const usernameField = document.querySelector(LOGIN_SELECTORS.UBER_USERNAME);
  if (!usernameField) {
    console.log("[ReEngage Login] UberEats username field not found");
    return false;
  }
  await typeIntoField(LOGIN_SELECTORS.UBER_USERNAME, username);
  simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));

  // Step 2: Wait for OTP or password screen to appear
  console.log("[ReEngage Login] Waiting for OTP or password screen...");
  let otpFields = null;
  let passwordField = null;
  for (let attempt = 0; attempt < 15; attempt++) {
    await sleep(2000);
    otpFields = document.querySelectorAll(LOGIN_SELECTORS.UBER_OTP);
    passwordField = document.querySelector(LOGIN_SELECTORS.UBER_PASSWORD);
    console.log(`[ReEngage Login] Attempt ${attempt + 1}: otpFields=${otpFields.length}, passwordField=${!!passwordField}`);
    if (otpFields.length > 0 || passwordField) break;
  }

  // Handle OTP if found
  if (otpFields && otpFields.length > 0) {
    console.log(`[ReEngage Login] OTP fields found (${otpFields.length}). Waiting for fresh OTP...`);

    // Wait a few seconds for the platform to send the new OTP
    await sleep(5000);

    // Retry OTP fetch up to 3 times (in case we get a stale one)
    let otpSuccess = false;
    for (let otpAttempt = 0; otpAttempt < 3 && !otpSuccess; otpAttempt++) {
      try {
        let otp = await fetchOtp(
          `https://internal.loopapplication.xyz/get_last_uber_otp?username=${encodeURIComponent(username)}`
        );
        otp = otp.replace(/"/g, "").trim();
        console.log(`[ReEngage Login] OTP attempt ${otpAttempt + 1}: received "${otp}" (${otp.length} chars)`);

        if (!otp || otp.length < 4) {
          console.log("[ReEngage Login] OTP too short, retrying in 5s...");
          await sleep(5000);
          continue;
        }

        // Re-query OTP fields in case they changed
        otpFields = document.querySelectorAll(LOGIN_SELECTORS.UBER_OTP);
        for (const [index, char] of otp.split("").entries()) {
          if (otpFields[index]) {
            await typeIntoFieldElement(otpFields[index], char);
            await sleep(500);
          }
        }
        await sleep(2000);
        simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));
        console.log("[ReEngage Login] OTP submitted");
        otpSuccess = true;

        // Check if OTP was rejected (fields still visible after submit)
        await sleep(3000);
        const stillOnOtp = document.querySelectorAll(LOGIN_SELECTORS.UBER_OTP).length > 0;
        if (stillOnOtp) {
          console.log("[ReEngage Login] OTP might be wrong (still on OTP screen), retrying in 5s...");
          otpSuccess = false;
          await sleep(5000);
        }
      } catch (e) {
        console.error(`[ReEngage Login] OTP attempt ${otpAttempt + 1} failed:`, e);
        await sleep(5000);
      }
    }
    if (!otpSuccess) {
      console.error("[ReEngage Login] All OTP attempts failed");
    }

    // After OTP, might need password
    await sleep(5000);
    passwordField = document.querySelector(LOGIN_SELECTORS.UBER_PASSWORD);
  }

  // Handle password if found
  if (passwordField) {
    console.log("[ReEngage Login] Password field found. Entering password...");
    await typeIntoField(LOGIN_SELECTORS.UBER_PASSWORD, password);
    simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));
    console.log("[ReEngage Login] Password submitted");
  }

  return true;
}

// ── Helpers ──

async function typeIntoField(selector, value) {
  const element = document.querySelector(selector);
  if (!element) return;
  element.value = "";
  for (const char of value.split("")) {
    element.value += char;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(60);
  }
}

async function typeIntoFieldElement(element, value) {
  if (!element) return;
  element.value = "";
  for (const char of value.split("")) {
    element.value += char;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(60);
  }
}

function simulateClick(element) {
  if (!element) return;
  ["mousedown", "click", "mouseup"].forEach((eventType) => {
    try {
      element.dispatchEvent(
        new MouseEvent(eventType, {
          view: window,
          bubbles: true,
          cancelable: true,
          buttons: 1,
        })
      );
    } catch (e) {}
  });
}

async function fetchOtp(url) {
  // Must go through the background worker: a direct fetch from this content
  // script carries the merchant portal's Origin, which the OTP backend's CORS
  // allowlist rejects (backend PR #16726). The worker's host_permissions
  // exempt it from CORS.
  const response = await chrome.runtime.sendMessage({ type: "FETCH_OTP", url });
  if (!response || !response.success) {
    console.error("[ReEngage Login] OTP fetch failed:", response && response.error);
    throw new Error(`OTP fetch failed: ${response ? response.error : "no response from background"}`);
  }
  return response.text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getDoorDashUrl(storeId) {
  const url = new URL("https://www.doordash.com/merchant/summary");
  if (storeId) url.searchParams.set("store_id", storeId);
  return url.toString();
}

function redirectIfNeeded(url, currentPrefix) {
  if (!url || window.location.href.startsWith(currentPrefix)) return;
  window.location.href = url;
}
