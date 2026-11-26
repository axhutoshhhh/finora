/**
 * Safe DOM rendering helpers for Finora views.
 * All dynamic text uses textContent or createElement (zero innerHTML with user strings).
 */

const ALLOWED_ICONS = new Set([
  "utensils",
  "house",
  "car",
  "shopping-bag",
  "book-open",
  "heart-pulse",
  "film",
  "repeat",
  "zap",
  "circle-ellipsis",
  "briefcase",
  "coins",
  "laptop",
  "graduation-cap",
  "building-2",
  "gift",
  "plus-circle",
  "arrow-up-right",
  "arrow-down-left",
]);

function makeIcon(name, extraClass = "") {
  const safeName = ALLOWED_ICONS.has(name) ? name : "circle-ellipsis";
  const span = document.createElement("span");
  span.className = extraClass ? `icon ${extraClass}` : "icon";
  span.setAttribute("data-icon", safeName);
  span.setAttribute("aria-hidden", "true");
  return span;
}

function makeCell(text, { className = "", dataLabel = "", tooltip = "" } = {}) {
  const td = document.createElement("td");
  if (className) {
    td.className = className;
  }
  if (dataLabel) {
    td.setAttribute("data-label", dataLabel);
  }
  if (tooltip) {
    td.title = tooltip;
  }
  td.textContent = text;
  return td;
}

function makeCategoryCell(tx) {
  const td = document.createElement("td");
  td.setAttribute("data-label", "Category");

  const wrap = document.createElement("span");
  wrap.className = "category-cell";

  const badge = document.createElement("span");
  badge.className = "category-badge";
  badge.appendChild(makeIcon(tx.category_icon, "icon-sm"));

  const label = document.createElement("span");
  label.textContent = tx.category_name || "Uncategorized";

  wrap.append(badge, label);
  td.appendChild(wrap);
  return td;
}

function makeTypeCell(tx) {
  const td = document.createElement("td");
  td.setAttribute("data-label", "Type");

  const tag = document.createElement("span");
  const isIncome = tx.entry_type === "income";
  tag.className = `type-tag ${isIncome ? "type-tag-income" : "type-tag-expense"}`;
  tag.appendChild(makeIcon(isIncome ? "arrow-down-left" : "arrow-up-right", "icon-sm"));

  const text = document.createElement("span");
  text.textContent = isIncome ? "Income" : "Expense";
  tag.appendChild(text);

  td.appendChild(tag);
  return td;
}

function makeAmountCell(tx) {
  const isIncome = tx.entry_type === "income";
  const td = document.createElement("td");
  td.setAttribute("data-label", "Amount");
  td.className = `col-amount tabular-nums ${isIncome ? "amount-positive" : "amount-negative"}`;
  td.textContent = tx.signed_amount_formatted;
  return td;
}

export function renderOverview(overviewData) {
  const balanceEl = document.getElementById("overview-balance");
  const sidebarBalEl = document.getElementById("sidebar-cash-balance");
  const incomeEl = document.getElementById("overview-income");
  const expenseEl = document.getElementById("overview-expense");
  const surplusEl = document.getElementById("overview-surplus");
  const monthIncLabel = document.getElementById("overview-month-label-inc");
  const monthExpLabel = document.getElementById("overview-month-label-exp");
  const surplusMeta = document.getElementById("overview-surplus-meta");
  const emptyBox = document.getElementById("overview-empty");
  const tableWrap = document.getElementById("overview-table-wrap");
  const viewAllBtn = document.getElementById("overview-view-all-btn");
  const tbody = document.getElementById("overview-recent-body");

  balanceEl.textContent = overviewData.total_balance_formatted;
  sidebarBalEl.textContent = overviewData.total_balance_formatted;

  const m = overviewData.month;
  incomeEl.textContent = m.income_formatted;
  expenseEl.textContent = m.expense_formatted;
  surplusEl.textContent = m.surplus_formatted;

  surplusEl.classList.remove("amount-positive", "amount-negative");
  if (m.surplus_minor > 0) {
    surplusEl.classList.add("amount-positive");
    surplusMeta.textContent = "Net surplus this month";
  } else if (m.surplus_minor < 0) {
    surplusEl.classList.add("amount-negative");
    surplusMeta.textContent = "Net deficit this month";
  } else {
    surplusMeta.textContent = "Income minus expenses";
  }

  monthIncLabel.textContent = m.label;
  monthExpLabel.textContent = m.label;

  tbody.replaceChildren();
  const recent = overviewData.recent_transactions || [];
  if (recent.length === 0) {
    emptyBox.hidden = false;
    tableWrap.hidden = true;
    viewAllBtn.hidden = true;
    return;
  }

  emptyBox.hidden = true;
  tableWrap.hidden = false;
  viewAllBtn.hidden = false;

  const frag = document.createDocumentFragment();
  for (const tx of recent) {
    const tr = document.createElement("tr");
    tr.append(
      makeCell(tx.tx_date, { className: "col-date tabular-nums", dataLabel: "Date" }),
      makeCategoryCell(tx),
      makeCell(tx.description || "—", {
        className: "col-desc",
        dataLabel: "Description",
        tooltip: tx.description || "",
      }),
      makeCell(tx.account_name, { className: "col-account", dataLabel: "Account" }),
      makeAmountCell(tx)
    );
    frag.appendChild(tr);
  }
  tbody.appendChild(frag);
}

export function renderTransactionsList(txData, { append = false } = {}) {
  const countEl = document.getElementById("tx-history-count");
  const emptyBox = document.getElementById("tx-empty");
  const tableWrap = document.getElementById("tx-table-wrap");
  const tbody = document.getElementById("tx-history-body");
  const loadMoreWrap = document.getElementById("tx-load-more-wrap");

  const items = txData.transactions || [];
  const total = txData.total_count ?? items.length;
  countEl.textContent = total === 1 ? "1 entry" : `${total} entries`;

  if (!append) {
    tbody.replaceChildren();
  }
  if (!append && items.length === 0) {
    emptyBox.hidden = false;
    tableWrap.hidden = true;
    if (loadMoreWrap) {
      loadMoreWrap.hidden = true;
    }
    return;
  }

  emptyBox.hidden = true;
  tableWrap.hidden = false;

  const frag = document.createDocumentFragment();
  for (const tx of items) {
    const tr = document.createElement("tr");
    tr.append(
      makeCell(tx.tx_date, { className: "col-date tabular-nums", dataLabel: "Date" }),
      makeCategoryCell(tx),
      makeCell(tx.description || "—", {
        className: "col-desc",
        dataLabel: "Description",
        tooltip: tx.description || "",
      }),
      makeTypeCell(tx),
      makeCell(tx.account_name, { className: "col-account", dataLabel: "Account" }),
      makeAmountCell(tx)
    );
    frag.appendChild(tr);
  }
  tbody.appendChild(frag);

  if (loadMoreWrap) {
    loadMoreWrap.hidden = tbody.rows.length >= total;
  }
}

export function renderSettings(settingsData) {
  document.getElementById("settings-currency").textContent = `${settingsData.currency} (₹)`;
  document.getElementById("settings-data-dir").textContent = settingsData.storage?.data_dir || "—";
  document.getElementById("settings-db-path").textContent = settingsData.storage?.database_path || "—";
  document.getElementById("settings-encryption-note").textContent =
    settingsData.storage?.encryption_note || "—";
  document.getElementById("settings-version").textContent = settingsData.version || "0.1.0";

  const radios = document.querySelectorAll('input[name="appearance"]');
  for (const radio of radios) {
    radio.checked = radio.value === settingsData.appearance;
  }
}
