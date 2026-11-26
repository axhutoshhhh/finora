/**
 * Main Finora frontend controller: client routing, data hydration, appearance sync, and shortcuts.
 */

import { api } from "./api.js";
import { initTransactionDialog } from "./dialog.js";
import { renderOverview, renderSettings, renderTransactionsList } from "./render.js";

const VIEW_META = {
  overview: { title: "Overview", path: "/" },
  transactions: { title: "Transactions", path: "/transactions" },
  settings: { title: "Settings", path: "/settings" },
};

const shellEl = document.getElementById("finora-shell");
const pageTitleEl = document.getElementById("page-title");
const pageSubtitleEl = document.getElementById("page-subtitle");
const liveStatusEl = document.getElementById("app-live-status");
const errorBanner = document.getElementById("global-error-banner");
const errorBannerText = document.getElementById("global-error-text");
const successBanner = document.getElementById("global-success-banner");
const successBannerText = document.getElementById("global-success-text");

const state = {
  activeView: shellEl?.dataset.initialView || "overview",
  appearance: shellEl?.dataset.initialAppearance || "system",
  lookups: {
    accounts: [],
    categories: [],
  },
  overviewMonthLabel: "",
  txLoadedCount: 0,
  successTimerId: null,
};

function showErrorBanner(message) {
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
    state.successTimerId = null;
  }
  successBanner.hidden = true;
  errorBannerText.textContent = message;
  errorBanner.hidden = false;
}

function showSuccessBanner(message) {
  errorBanner.hidden = true;
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
  }
  successBannerText.textContent = message;
  successBanner.hidden = false;
  liveStatusEl.textContent = message;
  state.successTimerId = window.setTimeout(() => {
    successBanner.hidden = true;
    state.successTimerId = null;
  }, 4000);
}

function clearBanners() {
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
    state.successTimerId = null;
  }
  errorBanner.hidden = true;
  successBanner.hidden = true;
}

function updateSystemAppearanceHint() {
  const hint = document.getElementById("system-appearance-hint");
  if (!hint) {
    return;
  }
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  hint.textContent = `Follows macOS (${prefersDark ? "currently dark" : "currently light"})`;
}

function applyColorSchemeMeta(metaValue) {
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) {
    meta.setAttribute("content", metaValue);
  }
}

function setActiveView(viewName, { pushHistory = true, moveFocus = false } = {}) {
  const target = VIEW_META[viewName] ? viewName : "overview";
  state.activeView = target;
  clearBanners();

  for (const name of Object.keys(VIEW_META)) {
    const panel = document.getElementById(`view-${name}`);
    if (panel) {
      panel.hidden = name !== target;
    }
    const navLink = document.querySelector(`[data-nav-view="${name}"]`);
    if (navLink) {
      if (name === target) {
        navLink.setAttribute("aria-current", "page");
      } else {
        navLink.removeAttribute("aria-current");
      }
    }
  }

  const meta = VIEW_META[target];
  pageTitleEl.textContent = meta.title;
  document.title = `${meta.title} | Finora`;
  pageSubtitleEl.textContent = target === "overview" ? state.overviewMonthLabel : "";

  if (pushHistory && window.location.pathname !== meta.path) {
    window.history.pushState({ view: target }, "", meta.path);
  }

  if (moveFocus) {
    pageTitleEl.focus();
  }
}

async function refreshAllData() {
  clearBanners();
  const [overview, txList, accountsRes, categoriesRes, settings] = await Promise.all([
    api.getOverview(),
    api.getTransactions(),
    api.getAccounts(),
    api.getCategories(),
    api.getSettings(),
  ]);

  state.lookups.accounts = accountsRes.accounts || [];
  state.lookups.categories = categoriesRes.categories || [];
  state.overviewMonthLabel = overview.month?.label || "";
  state.appearance = settings.appearance || "system";
  state.txLoadedCount = (txList.transactions || []).length;

  renderOverview(overview);
  renderTransactionsList(txList, { append: false });
  renderSettings(settings);
  applyColorSchemeMeta(settings.color_scheme_meta);

  if (state.activeView === "overview") {
    pageSubtitleEl.textContent = state.overviewMonthLabel;
  }
}

async function bootstrap() {
  updateSystemAppearanceHint();
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  mediaQuery.addEventListener("change", updateSystemAppearanceHint);

  setActiveView(state.activeView, { pushHistory: false, moveFocus: false });

  const txDialog = initTransactionDialog({
    getLookups: () => state.lookups,
    onSaved: async (tx) => {
      await refreshAllData();
      const kindLabel = tx.entry_type === "income" ? "Income" : "Expense";
      showSuccessBanner(`${kindLabel} of ${tx.amount_formatted} recorded in ${tx.category_name}.`);
    },
  });

  document.getElementById("new-tx-btn").addEventListener("click", () => txDialog.open());
  document.getElementById("overview-empty-add-btn").addEventListener("click", () => txDialog.open());
  document.getElementById("tx-empty-add-btn").addEventListener("click", () => txDialog.open());
  document
    .getElementById("overview-view-all-btn")
    .addEventListener("click", () => setActiveView("transactions", { moveFocus: true }));

  for (const navLink of document.querySelectorAll("[data-nav-view]")) {
    navLink.addEventListener("click", (e) => {
      e.preventDefault();
      const target = navLink.getAttribute("data-nav-view");
      setActiveView(target, { moveFocus: e.detail === 0 });
    });
  }

  window.addEventListener("popstate", () => {
    const path = window.location.pathname;
    const matched = Object.entries(VIEW_META).find(([, m]) => m.path === path);
    setActiveView(matched ? matched[0] : "overview", { pushHistory: false });
  });

  const loadMoreBtn = document.getElementById("tx-load-more-btn");
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", async () => {
      loadMoreBtn.disabled = true;
      try {
        const nextPage = await api.getTransactions(200, state.txLoadedCount);
        const batch = nextPage.transactions || [];
        state.txLoadedCount += batch.length;
        renderTransactionsList(nextPage, { append: true });
      } catch (err) {
        showErrorBanner(err instanceof Error ? err.message : "Failed to load more transactions.");
      } finally {
        loadMoreBtn.disabled = false;
      }
    });
  }

  // Appearance radio persistence
  for (const radio of document.querySelectorAll('input[name="appearance"]')) {
    radio.addEventListener("change", async () => {
      if (!radio.checked) {
        return;
      }
      const previous = state.appearance;
      try {
        const res = await api.updateAppearance(radio.value);
        state.appearance = res.appearance;
        applyColorSchemeMeta(res.color_scheme_meta);
        liveStatusEl.textContent = `Appearance updated to ${res.appearance}.`;
      } catch (err) {
        for (const candidate of document.querySelectorAll('input[name="appearance"]')) {
          candidate.checked = candidate.value === previous;
        }
        showErrorBanner(err instanceof Error ? err.message : "Failed to save appearance.");
      }
    });
  }

  // Native macOS menu / Cmd+N shortcut integration
  window.addEventListener("finora:new-transaction", () => txDialog.open());
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "n") {
      e.preventDefault();
      txDialog.open();
    }
  });

  try {
    await refreshAllData();
  } catch (err) {
    showErrorBanner(
      err instanceof Error ? err.message : "Unable to load local financial data."
    );
  }
}

bootstrap();
