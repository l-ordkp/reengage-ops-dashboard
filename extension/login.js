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

chrome.storage.local.get(
  ["login_username", "login_password", "login_platform", "login_store_id"],
  async (data) => {
    const username = data.login_username;
    const password = data.login_password;
    const platform = data.login_platform;
    const storeId = data.login_store_id;

    if (!platform || !username) return;

    console.log(`[ReEngage Login] Auto-login for ${platform}`);

    try {
      switch (platform) {
        case "UBEREATS":
          await loginUberEats(username, password, storeId);
          break;
        case "DOORDASH":
          await loginDoorDash(username, password, storeId);
          break;
      }
    } catch (e) {
      console.error("[ReEngage Login] Error:", e);
    }

    // Clean up credentials from storage
    chrome.storage.local.remove([
      "login_username",
      "login_password",
      "login_platform",
      "login_store_id",
    ]);
  }
);

// ── DoorDash Login ──
async function loginDoorDash(username, password, storeId) {
  await sleep(4000);

  // Step 1: Enter username
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_USERNAME)) {
    await typeIntoField(LOGIN_SELECTORS.DOORDASH_USERNAME, username);
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_MERCHANT_LOGIN_BUTTON));
  } else {
    redirectIfNeeded(getDoorDashUrl(storeId), "https://www.doordash.com/merchant");
    return;
  }

  await sleep(4000);

  // Step 2: Click "Use password" if shown
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_USE_PASSWORD_BUTTON)) {
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_USE_PASSWORD_BUTTON));
    await sleep(4000);
  }

  // Step 3: Enter password
  if (document.querySelector(LOGIN_SELECTORS.DOORDASH_PASSWORD)) {
    await typeIntoField(LOGIN_SELECTORS.DOORDASH_PASSWORD, password);
    simulateClick(document.querySelector(LOGIN_SELECTORS.DOORDASH_LOGIN_BUTTON));
  }

  await sleep(10000);

  // Step 4: Handle OTP if needed
  const otpField = document.querySelector(LOGIN_SELECTORS.DOORDASH_OTP);
  if (otpField) {
    let otp = await fetchOtp(
      `https://internal.loopapplication.xyz/get_last_otp?username=${encodeURIComponent(username)}`
    );
    otp = otp.replace(/"/g, "");
    await typeIntoField(LOGIN_SELECTORS.DOORDASH_OTP, otp);
    simulateClick(document.querySelector("#prism-modal-footer > button:nth-child(2)"));
    await sleep(4000);
  }
}

// ── UberEats Login ──
async function loginUberEats(username, password, storeId) {
  await sleep(4000);

  // Set redirect URL for after login
  if (storeId) {
    const nextUrl = `https://merchants.ubereats.com/manager/home/${storeId}`;
    const params = new URLSearchParams(window.location.search);
    if (!window.location.href.includes(storeId)) {
      params.set("next_url", nextUrl);
      const newUrl = window.location.origin + window.location.pathname + "?" + params.toString();
      window.history.pushState({ path: newUrl }, "", newUrl);
      window.location = newUrl;
      return;
    }
  }

  // Step 1: Enter username
  if (document.querySelector(LOGIN_SELECTORS.UBER_USERNAME)) {
    await typeIntoField(LOGIN_SELECTORS.UBER_USERNAME, username);
    simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));
  }

  await sleep(5000);

  // Step 2: Handle OTP if needed
  const otpFields = document.querySelectorAll(LOGIN_SELECTORS.UBER_OTP);
  if (otpFields.length > 0) {
    let otp = await fetchOtp(
      `https://internal.loopapplication.xyz/get_last_uber_otp?username=${encodeURIComponent(username)}`
    );
    otp = otp.replace(/"/g, "");
    for (const [index, char] of otp.split("").entries()) {
      await typeIntoFieldElement(otpFields[index], char);
      await sleep(500);
    }
    await sleep(4000);
    simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));
  }

  // Step 3: Enter password if needed
  if (document.querySelector(LOGIN_SELECTORS.UBER_PASSWORD)) {
    await typeIntoField(LOGIN_SELECTORS.UBER_PASSWORD, password);
    simulateClick(document.querySelector(LOGIN_SELECTORS.UBER_NEXT_BUTTON));
  }
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
  const response = await fetch(url);
  if (!response.ok) {
    console.error("[ReEngage Login] OTP fetch failed");
    throw new Error("OTP fetch failed");
  }
  return await response.text();
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
