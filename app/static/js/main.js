/**
 * Main Finora Phase 2 frontend controller: routing, search/filters, bulk actions, undo, shortcuts.
 */

import { ApiError, api } from "./api.js";
import {
  initAccountDialog,
  initAttachmentPreviewDialog,
  initBudgetDialog,
  initCategoryDialog,
  initConfirmDialog,
  initRefundDialog,
  initTransactionDialog,
} from "./dialog.js";
import {
  renderAccountsView,
  renderBudgetsView,
  renderOverview,
  renderSettings,
  renderSettingsCategories,
  renderSettingsTags,
  renderTransactionsList,
} from "./render.js";

const VIEW_META = {
  overview: { title: "Overview", path: "/" },
  transactions: { title: "Transactions", path: "/transactions" },
  accounts: { title: "Accounts", path: "/accounts" },
  budgets: { title: "Budgets", path: "/budgets" },
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
const undoBtn = document.getElementById("global-undo-btn");

const state = {
  activeView: shellEl?.dataset.initialView || "overview",
  appearance: shellEl?.dataset.initialAppearance || "system",
  lookups: {
    accounts: [],
    categories: [],
    tags: [],
  },
  overviewMonth: null,
  overviewMonthMeta: null,
  budgetMonth: null,
  budgetData: null,
  selectedAccountId: null,
  showArchivedAccounts: false,
  showArchivedCategories: false,
  txFilters: {
    q: "",
    period: "",
    date_from: "",
    date_to: "",
    entry_type: "",
    account_id: "",
    category_id: "",
    payment_method: "",
    tag_id: "",
    min_amount: "",
    max_amount: "",
    deleted: "active",
    sort: "newest",
  },
  txLoadedItems: [],
  txLoadedCount: 0,
  selectedTxIds: new Set(),
  txAbortController: null,
  searchDebounceId: null,
  undoQueueIds: [],
  successTimerId: null,
};

function showErrorBanner(message) {
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
    state.successTimerId = null;
  }
  successBanner.hidden = true;
  undoBtn.hidden = true;
  errorBannerText.textContent = message;
  errorBanner.hidden = false;
}

function showSuccessBanner(message, { undoIds = [] } = {}) {
  errorBanner.hidden = true;
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
  }
  state.undoQueueIds = undoIds;
  undoBtn.hidden = undoIds.length === 0;
  successBannerText.textContent = message;
  successBanner.hidden = false;
  liveStatusEl.textContent = message;
  state.successTimerId = window.setTimeout(() => {
    successBanner.hidden = true;
    undoBtn.hidden = true;
    state.undoQueueIds = [];
    state.successTimerId = null;
  }, undoIds.length > 0 ? 8000 : 4000);
}

function clearBanners() {
  if (state.successTimerId !== null) {
    window.clearTimeout(state.successTimerId);
    state.successTimerId = null;
  }
  errorBanner.hidden = true;
  successBanner.hidden = true;
  undoBtn.hidden = true;
  state.undoQueueIds = [];
}

function updateSystemAppearanceHint() {
  const hint = document.getElementById("system-appearance-hint");
  if (!hint) return;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  hint.textContent = `Follows macOS (${prefersDark ? "currently dark" : "currently light"})`;
}

function applyColorSchemeMeta(metaValue) {
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) meta.setAttribute("content", metaValue);
}

function setActiveView(viewName, { pushHistory = true, moveFocus = false } = {}) {
  const target = VIEW_META[viewName] ? viewName : "overview";
  state.activeView = target;
  clearBanners();

  for (const name of Object.keys(VIEW_META)) {
    const panel = document.getElementById(`view-${name}`);
    if (panel) panel.hidden = name !== target;
    const navLink = document.querySelector(`[data-nav-view="${name}"]`);
    if (navLink) {
      if (name === target) navLink.setAttribute("aria-current", "page");
      else navLink.removeAttribute("aria-current");
    }
  }

  const meta = VIEW_META[target];
  pageTitleEl.textContent = meta.title;
  document.title = `${meta.title} | Finora`;
  pageSubtitleEl.textContent =
    target === "overview" ? state.overviewMonthMeta?.label || "" : "";

  if (pushHistory && window.location.pathname !== meta.path) {
    window.history.pushState({ view: target }, "", meta.path);
  }
  if (moveFocus) pageTitleEl.focus();
}

function populateTransactionFilterDropdowns() {
  const acctSel = document.getElementById("tx-filter-account");
  const catSel = document.getElementById("tx-filter-category");
  const tagSel = document.getElementById("tx-filter-tag");
  const bulkCatSel = document.getElementById("tx-bulk-category-select");
  const bulkTagSel = document.getElementById("tx-bulk-tag-select");

  const prevAcct = acctSel.value;
  acctSel.replaceChildren(new Option("All accounts", ""));
  for (const a of state.lookups.accounts) {
    acctSel.appendChild(new Option(a.name, String(a.id)));
  }
  acctSel.value = prevAcct;

  const prevCat = catSel.value;
  catSel.replaceChildren(new Option("All categories", ""));
  bulkCatSel.replaceChildren(new Option("Assign category…", ""));
  for (const c of state.lookups.categories) {
    catSel.appendChild(new Option(`${c.name} (${c.kind})`, String(c.id)));
    bulkCatSel.appendChild(new Option(`${c.name} (${c.kind})`, String(c.id)));
  }
  catSel.value = prevCat;

  const prevTag = tagSel.value;
  tagSel.replaceChildren(new Option("All tags", ""));
  bulkTagSel.replaceChildren(new Option("Add tag…", ""));
  for (const t of state.lookups.tags) {
    tagSel.appendChild(new Option(`#${t.name}`, String(t.id)));
    bulkTagSel.appendChild(new Option(`#${t.name}`, String(t.id)));
  }
  tagSel.value = prevTag;
}

function syncBulkBar() {
  const bar = document.getElementById("tx-bulk-bar");
  const countEl = document.getElementById("tx-bulk-count");
  const selectAllCb = document.getElementById("tx-select-all-visible");
  const delBtn = document.getElementById("tx-bulk-delete-btn");
  const restBtn = document.getElementById("tx-bulk-restore-btn");

  const count = state.selectedTxIds.size;
  if (count === 0) {
    bar.hidden = true;
    selectAllCb.checked = false;
    return;
  }
  bar.hidden = false;
  countEl.textContent = `${count} selected`;
  const isTrash = state.txFilters.deleted === "deleted";
  delBtn.hidden = isTrash;
  restBtn.hidden = !isTrash;
  selectAllCb.checked =
    state.txLoadedItems.length > 0 &&
    state.txLoadedItems.every((tx) => state.selectedTxIds.has(tx.id));
}

function monthPresetRange(preset) {
  if (!preset) return {};
  const now = new Date();
  let year = now.getFullYear();
  let monthIdx = now.getMonth();
  if (preset === "previous_month") {
    monthIdx -= 1;
    if (monthIdx < 0) {
      monthIdx = 11;
      year -= 1;
    }
  }
  return { month: `${year}-${String(monthIdx + 1).padStart(2, "0")}` };
}

function buildTxQueryParams(offset = 0) {
  const f = state.txFilters;
  const preset = monthPresetRange(f.period);
  return {
    limit: 100,
    offset,
    q: f.q,
    month: !f.date_from && !f.date_to ? preset.month || "" : "",
    date_from: f.date_from,
    date_to: f.date_to,
    entry_type: f.entry_type,
    account_id: f.account_id,
    category_id: f.category_id,
    payment_method: f.payment_method,
    tag_id: f.tag_id,
    min_amount: f.min_amount,
    max_amount: f.max_amount,
    deleted: f.deleted,
    sort: f.sort,
  };
}

async function bootstrap() {
  updateSystemAppearanceHint();
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", updateSystemAppearanceHint);

  const askConfirm = initConfirmDialog();
  const previewAttachment = initAttachmentPreviewDialog();

  let txDialog;
  let refundDialog;
  let accountDialog;
  let budgetDialog;
  let categoryDialog;

  async function performUndo(ids) {
    if (!ids || ids.length === 0) return;
    try {
      if (ids.length === 1) {
        await api.restoreTransaction(ids[0]);
      } else {
        await api.bulkTransactions({ action: "restore", transaction_ids: ids });
      }
      state.undoQueueIds = [];
      await refreshAllData();
      showSuccessBanner("Restored transaction(s) back to ledger.");
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Failed to undo deletion.");
    }
  }

  async function refreshTransactions({ append = false } = {}) {
    if (state.txAbortController) {
      state.txAbortController.abort();
    }
    const ctrl = new AbortController();
    state.txAbortController = ctrl;
    const offset = append ? state.txLoadedCount : 0;

    try {
      const txList = await api.getTransactions(buildTxQueryParams(offset), { signal: ctrl.signal });
      const batch = txList.transactions || [];
      if (append) {
        state.txLoadedItems = [...state.txLoadedItems, ...batch];
        state.txLoadedCount += batch.length;
      } else {
        state.txLoadedItems = batch;
        state.txLoadedCount = batch.length;
        state.selectedTxIds.clear();
      }
      renderTransactionsList(txList, {
        append,
        selectedIds: state.selectedTxIds,
        onToggleSelect: (id, checked) => {
          if (checked) state.selectedTxIds.add(id);
          else state.selectedTxIds.delete(id);
          syncBulkBar();
        },
        onEdit: (tx) => txDialog.open({ tx }),
        onRefund: (tx) => refundDialog.open(tx),
        onDelete: async (tx) => {
          try {
            await api.deleteTransaction(tx.id);
            await refreshAllData();
            showSuccessBanner("Transaction moved to Trash.", { undoIds: [tx.id] });
          } catch (err) {
            showErrorBanner(err instanceof Error ? err.message : "Could not delete transaction.");
          }
        },
        onRestore: async (tx) => performUndo([tx.id]),
        onPurge: async (tx) => {
          const ok = await askConfirm({
            title: "Delete Permanently",
            message: `Permanently delete ${tx.merchant || tx.description || tx.amount_formatted}? This cannot be undone and removes attached receipts.`,
            confirmLabel: "Delete Forever",
          });
          if (!ok) return;
          try {
            await api.purgeTransaction(tx.id);
            await refreshAllData();
            showSuccessBanner("Transaction permanently deleted.");
          } catch (err) {
            showErrorBanner(err instanceof Error ? err.message : "Failed to purge transaction.");
          }
        },
        onPreviewAttachment: previewAttachment,
      });
      syncBulkBar();
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      showErrorBanner(err instanceof Error ? err.message : "Failed to load transactions.");
    }
  }

  async function refreshAccountsView() {
    const accountsRes = await api.getAccounts(state.showArchivedAccounts);
    const allAccts = accountsRes.accounts || [];
    if (
      allAccts.length > 0 &&
      !allAccts.some((a) => a.id === state.selectedAccountId)
    ) {
      state.selectedAccountId = allAccts[0].id;
    }
    const detail =
      state.selectedAccountId !== null
        ? await api.getAccountDetail(state.selectedAccountId).catch(() => null)
        : null;

    renderAccountsView(accountsRes, state.selectedAccountId, detail, {
      onSelectAccount: async (acctId) => {
        state.selectedAccountId = acctId;
        await refreshAccountsView();
      },
      onEditAccount: (acct) => accountDialog.open(acct),
      onTransferFrom: (acct) => {
        if (acct.is_liability) {
          txDialog.open({ mode: "transfer" });
          document.getElementById("tx-to-account").value = String(acct.id);
        } else {
          txDialog.open({ mode: "transfer", defaultFromAccountId: acct.id });
        }
      },
      onArchiveAccount: async (acct) => {
        try {
          await api.archiveAccount(acct.id, false);
          await refreshAllData();
          showSuccessBanner(`Account '${acct.name}' archived.`);
        } catch (err) {
          if (err instanceof ApiError && err.code === "confirm_nonzero_archive") {
            const ok = await askConfirm({
              title: "Archive Non-Zero Account",
              message: err.message,
              confirmLabel: "Archive Anyway",
            });
            if (!ok) return;
            await api.archiveAccount(acct.id, true);
            await refreshAllData();
            showSuccessBanner(`Account '${acct.name}' archived.`);
          } else {
            showErrorBanner(err instanceof Error ? err.message : "Could not archive account.");
          }
        }
      },
      onRestoreAccount: async (acct) => {
        try {
          await api.restoreAccount(acct.id);
          await refreshAllData();
          showSuccessBanner(`Account '${acct.name}' restored.`);
        } catch (err) {
          showErrorBanner(err instanceof Error ? err.message : "Could not restore account.");
        }
      },
    });
  }

  async function refreshBudgetsView() {
    const data = await api.getBudgets(state.budgetMonth);
    state.budgetData = data;
    state.budgetMonth = data.month;
    renderBudgetsView(data, {
      onEditCategoryBudget: (row) =>
        budgetDialog.openCategory({
          month: data.month,
          monthLabel: data.month_label,
          row,
        }),
    });
  }

  async function refreshTaxonomySettings() {
    const [allCatsRes, tagsRes] = await Promise.all([
      api.getCategories({ includeArchived: state.showArchivedCategories }),
      api.getTags(),
    ]);
    renderSettingsCategories(allCatsRes.categories || [], {
      onEdit: (cat) => categoryDialog.open(cat),
      onArchive: async (cat) => {
        try {
          await api.archiveCategory(cat.id);
          await refreshAllData();
          showSuccessBanner(`Category '${cat.name}' archived.`);
        } catch (err) {
          showErrorBanner(err instanceof Error ? err.message : "Failed to archive category.");
        }
      },
      onRestore: async (cat) => {
        try {
          await api.restoreCategory(cat.id);
          await refreshAllData();
          showSuccessBanner(`Category '${cat.name}' restored.`);
        } catch (err) {
          showErrorBanner(err instanceof Error ? err.message : "Failed to restore category.");
        }
      },
    });
    renderSettingsTags(tagsRes.tags || [], {
      onRename: async (tag) => {
        const next = window.prompt("Rename tag:", tag.name);
        if (!next || !next.trim()) return;
        try {
          await api.updateTag(tag.id, { name: next.trim() });
          await refreshAllData();
          showSuccessBanner(`Tag renamed to '#${next.trim()}'.`);
        } catch (err) {
          showErrorBanner(err instanceof Error ? err.message : "Failed to rename tag.");
        }
      },
      onDelete: async (tag) => {
        const ok = await askConfirm({
          title: "Delete Tag",
          message: `Remove '#${tag.name}'? Associated transactions remain intact.`,
          confirmLabel: "Delete Tag",
        });
        if (!ok) return;
        try {
          await api.deleteTag(tag.id);
          await refreshAllData();
          showSuccessBanner(`Tag '#${tag.name}' removed.`);
        } catch (err) {
          showErrorBanner(err instanceof Error ? err.message : "Failed to delete tag.");
        }
      },
    });
  }

  async function refreshAllData() {
    const [overview, activeAcctsRes, activeCatsRes, tagsRes, settings] = await Promise.all([
      api.getOverview(state.overviewMonth),
      api.getAccounts(false),
      api.getCategories({ includeArchived: false }),
      api.getTags(),
      api.getSettings(),
    ]);

    state.lookups.accounts = activeAcctsRes.accounts || [];
    state.lookups.categories = activeCatsRes.categories || [];
    state.lookups.tags = tagsRes.tags || [];
    state.overviewMonth = overview.month.key;
    state.overviewMonthMeta = overview.month;
    state.appearance = settings.appearance || "system";

    populateTransactionFilterDropdowns();
    renderOverview(overview, {
      onOpenAccount: (acctId) => {
        state.selectedAccountId = acctId;
        setActiveView("accounts", { moveFocus: true });
        refreshAccountsView();
      },
    });
    renderSettings(settings);
    applyColorSchemeMeta(settings.color_scheme_meta);

    if (state.activeView === "overview") {
      pageSubtitleEl.textContent = overview.month.label;
    }

    await Promise.all([
      refreshTransactions({ append: false }),
      refreshAccountsView(),
      refreshBudgetsView(),
      refreshTaxonomySettings(),
    ]);
  }

  txDialog = initTransactionDialog({
    getLookups: () => state.lookups,
    onPreviewAttachment: previewAttachment,
    onSaved: async ({ transaction, edited, updatedQuietly } = {}) => {
      await refreshAllData();
      if (updatedQuietly || !transaction) return;
      const actionWord = edited ? "updated" : "recorded";
      showSuccessBanner(
        `${transaction.entry_type[0].toUpperCase()}${transaction.entry_type.slice(1)} of ${transaction.amount_formatted} ${actionWord}.`
      );
    },
  });

  refundDialog = initRefundDialog({
    getLookups: () => state.lookups,
    onSaved: async (tx) => {
      await refreshAllData();
      showSuccessBanner(`Refund of ${tx.amount_formatted} recorded.`);
    },
  });

  accountDialog = initAccountDialog({
    onSaved: async (acct) => {
      state.selectedAccountId = acct.id;
      await refreshAllData();
      showSuccessBanner(`Account '${acct.name}' saved.`);
    },
  });

  budgetDialog = initBudgetDialog({
    onSaved: async () => {
      await refreshAllData();
      showSuccessBanner("Monthly budget updated.");
    },
  });

  categoryDialog = initCategoryDialog({
    onSaved: async () => {
      await refreshAllData();
      showSuccessBanner("Category saved.");
    },
  });

  setActiveView(state.activeView, { pushHistory: false, moveFocus: false });

  // Navigation & Primary Buttons
  document.getElementById("new-tx-btn").addEventListener("click", () => txDialog.open());
  document.getElementById("overview-empty-add-btn").addEventListener("click", () => txDialog.open());
  document.getElementById("tx-empty-add-btn").addEventListener("click", () => txDialog.open());
  document
    .getElementById("overview-transfer-btn")
    .addEventListener("click", () => txDialog.open({ mode: "transfer" }));
  document
    .getElementById("overview-view-all-btn")
    .addEventListener("click", () => setActiveView("transactions", { moveFocus: true }));
  document
    .getElementById("overview-manage-accounts-btn")
    .addEventListener("click", () => setActiveView("accounts", { moveFocus: true }));
  document
    .getElementById("overview-manage-budgets-btn")
    .addEventListener("click", () => setActiveView("budgets", { moveFocus: true }));

  undoBtn.addEventListener("click", () => performUndo(state.undoQueueIds));

  // Overview Month Stepper
  document.getElementById("overview-prev-month").addEventListener("click", async () => {
    if (state.overviewMonthMeta?.previous_key) {
      state.overviewMonth = state.overviewMonthMeta.previous_key;
      await refreshAllData();
    }
  });
  document.getElementById("overview-next-month").addEventListener("click", async () => {
    if (state.overviewMonthMeta?.next_key) {
      state.overviewMonth = state.overviewMonthMeta.next_key;
      await refreshAllData();
    }
  });

  // Accounts actions
  document.getElementById("accounts-new-btn").addEventListener("click", () => accountDialog.open());
  document
    .getElementById("accounts-transfer-btn")
    .addEventListener("click", () => txDialog.open({ mode: "transfer" }));
  document.getElementById("accounts-show-archived").addEventListener("change", async (e) => {
    state.showArchivedAccounts = e.target.checked;
    await refreshAccountsView();
  });

  // Budgets actions
  document.getElementById("budgets-prev-month").addEventListener("click", async () => {
    if (state.budgetData?.previous_month) {
      state.budgetMonth = state.budgetData.previous_month;
      await refreshBudgetsView();
    }
  });
  document.getElementById("budgets-next-month").addEventListener("click", async () => {
    if (state.budgetData?.next_month) {
      state.budgetMonth = state.budgetData.next_month;
      await refreshBudgetsView();
    }
  });
  document.getElementById("budgets-edit-overall-btn").addEventListener("click", () => {
    if (state.budgetData) {
      budgetDialog.openOverall({
        month: state.budgetData.month,
        monthLabel: state.budgetData.month_label,
        overall: state.budgetData.overall,
      });
    }
  });
  document.getElementById("budgets-copy-prev-btn").addEventListener("click", async () => {
    if (!state.budgetData) return;
    try {
      await api.copyBudgets({
        target_month: state.budgetData.month,
        source_month: state.budgetData.previous_month,
      });
      await refreshAllData();
      showSuccessBanner(`Copied budgets from ${state.budgetData.previous_month}.`);
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Could not copy previous budget.");
    }
  });

  // Transactions Search / Filters / Bulk
  const filterBindings = [
    ["tx-filter-sort", "sort"],
    ["tx-filter-deleted", "deleted"],
    ["tx-filter-period", "period"],
    ["tx-filter-date-from", "date_from"],
    ["tx-filter-date-to", "date_to"],
    ["tx-filter-type", "entry_type"],
    ["tx-filter-account", "account_id"],
    ["tx-filter-category", "category_id"],
    ["tx-filter-method", "payment_method"],
    ["tx-filter-tag", "tag_id"],
  ];
  for (const [id, key] of filterBindings) {
    document.getElementById(id).addEventListener("change", (e) => {
      state.txFilters[key] = e.target.value;
      refreshTransactions({ append: false });
    });
  }
  const searchInput = document.getElementById("tx-search-input");
  const scheduleSearch = () => {
    if (state.searchDebounceId !== null) window.clearTimeout(state.searchDebounceId);
    state.searchDebounceId = window.setTimeout(() => {
      state.txFilters.q = searchInput.value;
      state.txFilters.min_amount = document.getElementById("tx-filter-min").value;
      state.txFilters.max_amount = document.getElementById("tx-filter-max").value;
      refreshTransactions({ append: false });
    }, 180);
  };
  searchInput.addEventListener("input", scheduleSearch);
  document.getElementById("tx-filter-min").addEventListener("input", scheduleSearch);
  document.getElementById("tx-filter-max").addEventListener("input", scheduleSearch);

  document.getElementById("tx-filters-toggle-btn").addEventListener("click", (e) => {
    const grid = document.getElementById("tx-advanced-filters");
    const nextHidden = !grid.hidden;
    grid.hidden = nextHidden;
    e.currentTarget.setAttribute("aria-expanded", String(!nextHidden));
  });

  document.getElementById("tx-filters-reset-btn").addEventListener("click", () => {
    Object.assign(state.txFilters, {
      q: "",
      period: "",
      date_from: "",
      date_to: "",
      entry_type: "",
      account_id: "",
      category_id: "",
      payment_method: "",
      tag_id: "",
      min_amount: "",
      max_amount: "",
      deleted: "active",
      sort: "newest",
    });
    searchInput.value = "";
    document.getElementById("tx-filter-min").value = "";
    document.getElementById("tx-filter-max").value = "";
    for (const [id, key] of filterBindings) {
      document.getElementById(id).value = state.txFilters[key];
    }
    refreshTransactions({ append: false });
  });

  document.getElementById("tx-load-more-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    await refreshTransactions({ append: true });
    btn.disabled = false;
  });

  document.getElementById("tx-select-all-visible").addEventListener("change", (e) => {
    if (e.target.checked) {
      for (const tx of state.txLoadedItems) state.selectedTxIds.add(tx.id);
    } else {
      state.selectedTxIds.clear();
    }
    for (const cb of document.querySelectorAll('#tx-history-body input[type="checkbox"]')) {
      cb.checked = e.target.checked;
    }
    syncBulkBar();
  });

  document.getElementById("tx-bulk-clear-btn").addEventListener("click", () => {
    state.selectedTxIds.clear();
    for (const cb of document.querySelectorAll('#tx-history-body input[type="checkbox"]')) {
      cb.checked = false;
    }
    syncBulkBar();
  });

  document.getElementById("tx-bulk-apply-cat-btn").addEventListener("click", async () => {
    const catId = Number(document.getElementById("tx-bulk-category-select").value);
    if (!catId || state.selectedTxIds.size === 0) return;
    try {
      const res = await api.bulkTransactions({
        action: "set_category",
        transaction_ids: Array.from(state.selectedTxIds),
        category_id: catId,
      });
      state.selectedTxIds.clear();
      await refreshAllData();
      showSuccessBanner(`Updated category on ${res.affected_count} transactions.`);
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Bulk category update failed.");
    }
  });

  document.getElementById("tx-bulk-apply-tag-btn").addEventListener("click", async () => {
    const tagId = Number(document.getElementById("tx-bulk-tag-select").value);
    if (!tagId || state.selectedTxIds.size === 0) return;
    try {
      const res = await api.bulkTransactions({
        action: "add_tag",
        transaction_ids: Array.from(state.selectedTxIds),
        tag_id: tagId,
      });
      state.selectedTxIds.clear();
      await refreshAllData();
      showSuccessBanner(`Tagged ${res.affected_count} transactions.`);
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Bulk tagging failed.");
    }
  });

  document.getElementById("tx-bulk-delete-btn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedTxIds);
    if (ids.length === 0) return;
    const ok = await askConfirm({
      title: "Delete Selected Transactions",
      message: `Move ${ids.length} selected transaction(s) to Trash? You can undo or restore them anytime.`,
      confirmLabel: "Move to Trash",
    });
    if (!ok) return;
    try {
      const res = await api.bulkTransactions({ action: "delete", transaction_ids: ids });
      state.selectedTxIds.clear();
      await refreshAllData();
      showSuccessBanner(`Moved ${res.affected_count} transactions to Trash.`, { undoIds: ids });
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Bulk delete failed.");
    }
  });

  document.getElementById("tx-bulk-restore-btn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedTxIds);
    if (ids.length === 0) return;
    await performUndo(ids);
    state.selectedTxIds.clear();
    syncBulkBar();
  });

  // Settings Sub-Tabs (accessible tablist + keyboard arrows)
  const settingsTabs = Array.from(document.querySelectorAll("[data-settings-tab]"));
  function activateSettingsTab(tabBtn) {
    const key = tabBtn.getAttribute("data-settings-tab");
    for (const btn of settingsTabs) {
      const isSel = btn === tabBtn;
      btn.setAttribute("aria-selected", String(isSel));
      btn.tabIndex = isSel ? 0 : -1;
      const panel = document.getElementById(`settings-panel-${btn.getAttribute("data-settings-tab")}`);
      if (panel) panel.hidden = !isSel;
    }
    if (key === "categories" || key === "tags") {
      refreshTaxonomySettings();
    }
  }
  for (const btn of settingsTabs) {
    btn.addEventListener("click", () => activateSettingsTab(btn));
    btn.addEventListener("keydown", (e) => {
      const idx = settingsTabs.indexOf(btn);
      if (e.key === "ArrowRight") {
        e.preventDefault();
        const next = settingsTabs[(idx + 1) % settingsTabs.length];
        activateSettingsTab(next);
        next.focus();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        const prev = settingsTabs[(idx - 1 + settingsTabs.length) % settingsTabs.length];
        activateSettingsTab(prev);
        prev.focus();
      }
    });
  }

  document.getElementById("settings-new-cat-btn").addEventListener("click", () => categoryDialog.open());
  document.getElementById("settings-cat-show-archived").addEventListener("change", (e) => {
    state.showArchivedCategories = e.target.checked;
    refreshTaxonomySettings();
  });

  document.getElementById("settings-tag-create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const inp = document.getElementById("settings-tag-name-input");
    const name = inp.value.trim();
    if (!name) return;
    try {
      await api.createTag({ name });
      inp.value = "";
      await refreshAllData();
      showSuccessBanner(`Tag '#${name}' created.`);
    } catch (err) {
      showErrorBanner(err instanceof Error ? err.message : "Could not create tag.");
    }
  });

  // Navigation Links & Popstate
  for (const navLink of document.querySelectorAll("[data-nav-view]")) {
    navLink.addEventListener("click", (e) => {
      e.preventDefault();
      setActiveView(navLink.getAttribute("data-nav-view"), { moveFocus: e.detail === 0 });
    });
  }

  window.addEventListener("popstate", () => {
    const path = window.location.pathname;
    const matched = Object.entries(VIEW_META).find(([, m]) => m.path === path);
    setActiveView(matched ? matched[0] : "overview", { pushHistory: false });
  });

  // Appearance radio persistence
  for (const radio of document.querySelectorAll('input[name="appearance"]')) {
    radio.addEventListener("change", async () => {
      if (!radio.checked) return;
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

  // Native macOS menu & keyboard shortcuts (without hijacking text-editing Cmd+Z inside inputs)
  window.addEventListener("finora:new-transaction", () => txDialog.open());
  window.addEventListener("keydown", (e) => {
    if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
    const tag = document.activeElement?.tagName;
    const inTextField = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    const key = e.key.toLowerCase();

    if (key === "n" && !e.shiftKey) {
      e.preventDefault();
      txDialog.open();
    } else if (key === "f" && !e.shiftKey) {
      e.preventDefault();
      if (state.activeView !== "transactions") setActiveView("transactions");
      searchInput.focus();
    } else if (key === "1") {
      e.preventDefault();
      setActiveView("overview", { moveFocus: true });
    } else if (key === "2") {
      e.preventDefault();
      setActiveView("transactions", { moveFocus: true });
    } else if (key === "3") {
      e.preventDefault();
      setActiveView("accounts", { moveFocus: true });
    } else if (key === "4") {
      e.preventDefault();
      setActiveView("budgets", { moveFocus: true });
    } else if (e.key === ",") {
      e.preventDefault();
      setActiveView("settings", { moveFocus: true });
    } else if (key === "z" && !e.shiftKey && !inTextField && state.undoQueueIds.length > 0) {
      e.preventDefault();
      performUndo(state.undoQueueIds);
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
