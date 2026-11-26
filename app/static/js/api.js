/**
 * Secured API client for Finora.
 * Holds the ephemeral per-launch token strictly inside an unexported module closure.
 */

let _launchToken = null;
let _tokenPromise = null;

async function resolveLaunchToken() {
  if (_launchToken) {
    return _launchToken;
  }
  if (_tokenPromise) {
    return _tokenPromise;
  }

  _tokenPromise = new Promise((resolve, reject) => {
    // Path 1: Python desktop launcher delivered token before ES module initialized.
    if (typeof window.__finoraPendingAuth === "string" && window.__finoraPendingAuth.length > 0) {
      const token = window.__finoraPendingAuth;
      delete window.__finoraPendingAuth;
      _launchToken = token;
      resolve(token);
      return;
    }

    // Path 2: E2E browser harness stubbed pywebview bridge.
    if (window.pywebview?.api?.get_launch_token && !window.__finoraUseRunJsBridge) {
      Promise.resolve(window.pywebview.api.get_launch_token())
        .then((token) => {
          if (!token || typeof token !== "string") {
            reject(new Error("Desktop authorization token is unavailable."));
            return;
          }
          _launchToken = token;
          resolve(token);
        })
        .catch(reject);
      return;
    }

    // Path 3: Wait for CSP-safe window.run_js() handshake from desktop launcher.
    const timeoutId = window.setTimeout(() => {
      delete window.__finoraSetAuth;
      reject(
        new Error(
          "Finora's desktop security bridge is not attached. Please launch Finora as a desktop app."
        )
      );
    }, 5000);

    window.__finoraSetAuth = (token) => {
      window.clearTimeout(timeoutId);
      delete window.__finoraSetAuth;
      if (!token || typeof token !== "string") {
        reject(new Error("Desktop authorization token is unavailable."));
        return;
      }
      _launchToken = token;
      resolve(token);
    };
  });

  return _tokenPromise;
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = "api_error", field = null } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

async function requestJson(path, { method = "GET", body = null } = {}) {
  const token = await resolveLaunchToken();
  const headers = {
    "X-Finora-Token": token,
  };
  const init = {
    method,
    headers,
    credentials: "same-origin",
  };

  if (body !== null) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(path, init);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const err = payload?.error ?? {};
    throw new ApiError(err.message || `Request failed (${response.status}).`, {
      status: response.status,
      code: err.code || "request_failed",
      field: err.field || null,
    });
  }

  return payload;
}

export const api = {
  getOverview(month = null) {
    const query = month ? `?month=${encodeURIComponent(month)}` : "";
    return requestJson(`/api/overview${query}`);
  },
  getTransactions(limit = 200, offset = 0) {
    return requestJson(`/api/transactions?limit=${limit}&offset=${offset}`);
  },
  createTransaction(payload) {
    return requestJson("/api/transactions", { method: "POST", body: payload });
  },
  getCategories(kind = null) {
    const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    return requestJson(`/api/categories${query}`);
  },
  getAccounts() {
    return requestJson("/api/accounts");
  },
  getSettings() {
    return requestJson("/api/settings");
  },
  updateAppearance(appearance) {
    return requestJson("/api/settings/appearance", {
      method: "PUT",
      body: { appearance },
    });
  },
};
