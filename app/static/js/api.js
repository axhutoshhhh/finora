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
    if (typeof window.__finoraPendingAuth === "string" && window.__finoraPendingAuth.length > 0) {
      const token = window.__finoraPendingAuth;
      delete window.__finoraPendingAuth;
      _launchToken = token;
      resolve(token);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      delete window.__finoraSetAuth;
      _tokenPromise = null;
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
        _tokenPromise = null;
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

export async function requestJson(path, { method = "GET", body = null, signal = null } = {}) {
  const token = await resolveLaunchToken();
  const headers = {
    "X-Finora-Token": token,
  };
  const init = {
    method,
    headers,
    credentials: "same-origin",
  };
  if (signal) {
    init.signal = signal;
  }
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

async function uploadMultipart(path, file) {
  const token = await resolveLaunchToken();
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(path, {
    method: "POST",
    headers: { "X-Finora-Token": token },
    body: formData,
    credentials: "same-origin",
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const err = payload?.error ?? {};
    throw new ApiError(err.message || `Upload failed (${response.status}).`, {
      status: response.status,
      code: err.code || "upload_failed",
      field: err.field || null,
    });
  }
  return payload;
}

async function fetchAttachmentBlob(attachmentId) {
  const token = await resolveLaunchToken();
  const response = await fetch(`/api/attachments/${attachmentId}`, {
    method: "GET",
    headers: { "X-Finora-Token": token },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new ApiError(`Unable to load attachment (${response.status}).`, {
      status: response.status,
    });
  }
  return await response.blob();
}

function buildQuery(params = {}) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && String(v).trim() !== "") {
      sp.set(k, String(v));
    }
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  getOverview(month = null) {
    return requestJson(`/api/overview${buildQuery({ month })}`);
  },
  getTransactions(params = {}, { signal = null } = {}) {
    if (typeof params === "number") {
      // Compatibility signature (limit, offset)
      return requestJson(`/api/transactions${buildQuery({ limit: params })}`, { signal });
    }
    return requestJson(`/api/transactions${buildQuery(params)}`, { signal });
  },
  getTransaction(id) {
    return requestJson(`/api/transactions/${id}`);
  },
  createTransaction(payload) {
    return requestJson("/api/transactions", { method: "POST", body: payload });
  },
  updateTransaction(id, payload) {
    return requestJson(`/api/transactions/${id}`, { method: "PATCH", body: payload });
  },
  deleteTransaction(id) {
    return requestJson(`/api/transactions/${id}`, { method: "DELETE" });
  },
  restoreTransaction(id) {
    return requestJson(`/api/transactions/${id}/restore`, { method: "POST" });
  },
  purgeTransaction(id) {
    return requestJson(`/api/transactions/${id}/purge`, { method: "DELETE" });
  },
  bulkTransactions(payload) {
    return requestJson("/api/transactions/bulk", { method: "POST", body: payload });
  },
  createTransfer(payload) {
    return requestJson("/api/transfers", { method: "POST", body: payload });
  },
  getRefunds(transactionId) {
    return requestJson(`/api/transactions/${transactionId}/refunds`);
  },
  createRefund(transactionId, payload) {
    return requestJson(`/api/transactions/${transactionId}/refunds`, {
      method: "POST",
      body: payload,
    });
  },
  uploadAttachment(transactionId, file) {
    return uploadMultipart(`/api/transactions/${transactionId}/attachments`, file);
  },
  fetchAttachmentBlob,
  deleteAttachment(attachmentId) {
    return requestJson(`/api/attachments/${attachmentId}`, { method: "DELETE" });
  },
  getAccounts(includeArchived = false) {
    return requestJson(`/api/accounts${buildQuery({ include_archived: includeArchived ? 1 : 0 })}`);
  },
  getAccountDetail(id) {
    return requestJson(`/api/accounts/${id}`);
  },
  createAccount(payload) {
    return requestJson("/api/accounts", { method: "POST", body: payload });
  },
  updateAccount(id, payload) {
    return requestJson(`/api/accounts/${id}`, { method: "PATCH", body: payload });
  },
  archiveAccount(id, confirmNonzero = false) {
    return requestJson(`/api/accounts/${id}/archive`, {
      method: "POST",
      body: { confirm_nonzero: confirmNonzero },
    });
  },
  restoreAccount(id) {
    return requestJson(`/api/accounts/${id}/restore`, { method: "POST" });
  },
  getCategories({ kind = null, includeArchived = false } = {}) {
    return requestJson(
      `/api/categories${buildQuery({ kind, include_archived: includeArchived ? 1 : 0 })}`
    );
  },
  createCategory(payload) {
    return requestJson("/api/categories", { method: "POST", body: payload });
  },
  updateCategory(id, payload) {
    return requestJson(`/api/categories/${id}`, { method: "PATCH", body: payload });
  },
  archiveCategory(id) {
    return requestJson(`/api/categories/${id}/archive`, { method: "POST" });
  },
  restoreCategory(id) {
    return requestJson(`/api/categories/${id}/restore`, { method: "POST" });
  },
  getTags() {
    return requestJson("/api/tags");
  },
  createTag(payload) {
    return requestJson("/api/tags", { method: "POST", body: payload });
  },
  updateTag(id, payload) {
    return requestJson(`/api/tags/${id}`, { method: "PATCH", body: payload });
  },
  deleteTag(id) {
    return requestJson(`/api/tags/${id}`, { method: "DELETE" });
  },
  getBudgets(month = null) {
    return requestJson(`/api/budgets${buildQuery({ month })}`);
  },
  setCategoryBudget(payload) {
    return requestJson("/api/budgets/category", { method: "PUT", body: payload });
  },
  deleteCategoryBudget(categoryId, month) {
    return requestJson(`/api/budgets/category/${categoryId}${buildQuery({ month })}`, {
      method: "DELETE",
    });
  },
  setOverallBudget(payload) {
    return requestJson("/api/budgets/overall", { method: "PUT", body: payload });
  },
  deleteOverallBudget(month) {
    return requestJson(`/api/budgets/overall${buildQuery({ month })}`, { method: "DELETE" });
  },
  copyBudgets(payload) {
    return requestJson("/api/budgets/copy", { method: "POST", body: payload });
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
