/**
 * Safe DOM rendering helpers for all five Finora Phase 2 views.
 * Zero innerHTML with user strings; all text uses textContent or createElement.
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
  "arrow-left-right",
  "landmark",
  "piggy-bank",
  "credit-card",
  "wallet",
  "pie-chart",
  "tag",
  "folder",
  "shield-check",
  "paperclip",
  "split",
  "undo-2",
  "trash-2",
  "archive",
  "archive-restore",
  "pencil",
  "copy",
  "eye",
  "download",
  "chevron-down",
  "check-circle-2",
  "alert-circle",
]);

const PAYMENT_METHOD_LABELS = {
  cash: "Cash",
  upi: "UPI",
  debit_card: "Debit Card",
  credit_card: "Credit Card",
  bank_transfer: "Bank Transfer",
  other: "",
};

export function makeIcon(name, extraClass = "") {
  const safeName = ALLOWED_ICONS.has(name) ? name : "circle-ellipsis";
  const span = document.createElement("span");
  span.className = extraClass ? `icon ${extraClass}` : "icon";
  span.setAttribute("data-icon", safeName);
  span.setAttribute("aria-hidden", "true");
  return span;
}

function makeActionBtn(iconName, label, onClick, { className = "btn-icon" } = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.title = label;
  btn.setAttribute("aria-label", label);
  btn.appendChild(makeIcon(iconName, "icon-sm"));
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  return btn;
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
  let cls = "type-tag-expense";
  let icon = "arrow-up-right";
  let textLabel = "Expense";
  if (tx.entry_type === "income") {
    cls = "type-tag-income";
    icon = "arrow-down-left";
    textLabel = "Income";
  } else if (tx.entry_type === "refund") {
    cls = "type-tag-income";
    icon = "undo-2";
    textLabel = "Refund";
  } else if (tx.entry_type === "transfer") {
    cls = "type-tag-neutral";
    icon = "arrow-left-right";
    textLabel = tx.transfer_subtype === "credit_card_repayment" ? "Card Pay" : "Transfer";
  }

  tag.className = `type-tag ${cls}`;
  tag.appendChild(makeIcon(icon, "icon-sm"));
  const span = document.createElement("span");
  span.textContent = textLabel;
  tag.appendChild(span);

  td.appendChild(tag);
  return td;
}

function makeAmountCell(tx) {
  const td = document.createElement("td");
  td.setAttribute("data-label", "Amount");
  let cls = "col-amount tabular-nums ";
  if (tx.entry_type === "income" || tx.entry_type === "refund") {
    cls += "amount-positive";
  } else if (tx.entry_type === "expense") {
    cls += "amount-negative";
  }
  td.className = cls.trim();
  td.textContent = tx.signed_amount_formatted;
  return td;
}

function makeDetailsCell(tx, { onPreviewAttachment, compact = false } = {}) {
  const td = document.createElement("td");
  td.setAttribute("data-label", compact ? "Merchant & Note" : "Merchant & Details");
  td.className = "col-desc";

  const titleParts = [];
  if (tx.merchant) {
    titleParts.push(tx.merchant);
  }
  if (tx.description) {
    titleParts.push(tx.description);
  }
  const primaryText = titleParts.join(" — ") || "—";
  const primary = document.createElement("div");
  primary.className = "tx-primary-line";
  primary.title = primaryText;
  primary.textContent = primaryText;
  td.appendChild(primary);

  const metaItems = [];
  const pmLabel = PAYMENT_METHOD_LABELS[tx.payment_method] || "";
  if (pmLabel && tx.entry_type !== "transfer") {
    const pm = document.createElement("span");
    pm.textContent = pmLabel;
    metaItems.push(pm);
  }
  if (tx.refunded_minor > 0) {
    const rf = document.createElement("span");
    rf.textContent = `Refunded ${tx.refunded_formatted}`;
    metaItems.push(rf);
  }
  for (const t of tx.tags || []) {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.textContent = `#${t.name}`;
    metaItems.push(chip);
  }
  if (!compact) {
    for (const att of tx.attachments || []) {
      const attBtn = document.createElement("button");
      attBtn.type = "button";
      attBtn.className = "att-pill-btn";
      attBtn.appendChild(makeIcon("paperclip", "icon-sm"));
      const fn = document.createElement("span");
      fn.textContent = att.original_filename;
      attBtn.appendChild(fn);
      attBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (onPreviewAttachment) {
          onPreviewAttachment(att);
        }
      });
      metaItems.push(attBtn);
    }
  }

  if (metaItems.length > 0) {
    const sec = document.createElement("div");
    sec.className = "tx-secondary-line";
    sec.append(...metaItems);
    td.appendChild(sec);
  }

  if (!compact && tx.is_split && Array.isArray(tx.postings) && tx.postings.length > 1) {
    const detailsWrap = document.createElement("div");
    detailsWrap.className = "split-details-list";
    detailsWrap.hidden = true;

    for (const p of tx.postings) {
      const row = document.createElement("div");
      row.className = "split-details-row";
      const catSpan = document.createElement("span");
      catSpan.textContent = p.category_name || "Category";
      const amtSpan = document.createElement("span");
      amtSpan.className = "tabular-nums";
      amtSpan.textContent = p.amount_formatted;
      row.append(catSpan, amtSpan);
      detailsWrap.appendChild(row);
    }

    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "btn-link btn-sm";
    toggleBtn.textContent = `${tx.postings.length} split categories`;
    toggleBtn.addEventListener("click", () => {
      const nextHidden = !detailsWrap.hidden;
      detailsWrap.hidden = nextHidden;
      toggleBtn.textContent = nextHidden
        ? `${tx.postings.length} split categories`
        : "Hide splits";
    });
    td.append(toggleBtn, detailsWrap);
  }

  return td;
}

export function renderOverview(overviewData, { onOpenAccount } = {}) {
  const pos = overviewData.positions || {
    net_worth_formatted: overviewData.total_balance_formatted,
    total_assets_formatted: overviewData.total_balance_formatted,
    total_liabilities_formatted: "₹0.00",
  };
  document.getElementById("overview-balance").textContent = overviewData.total_balance_formatted;
  document.getElementById("overview-assets").textContent = pos.total_assets_formatted;
  document.getElementById("overview-liabilities-meta").textContent =
    `Card debt: ${pos.total_liabilities_formatted}`;
  document.getElementById("sidebar-assets-balance").textContent = pos.total_assets_formatted;
  document.getElementById("sidebar-liabilities-balance").textContent =
    pos.total_liabilities_formatted;
  document.getElementById("sidebar-cash-balance").textContent = pos.net_worth_formatted;

  const m = overviewData.month;
  document.getElementById("overview-month-picker-label").textContent = m.label;
  document.getElementById("overview-income").textContent = m.income_formatted;
  document.getElementById("overview-expense").textContent =
    m.net_expense_formatted || m.expense_formatted;
  document.getElementById("overview-month-label-inc").textContent = m.label;
  document.getElementById("overview-month-label-exp").textContent =
    `Gross ${m.gross_expense_formatted || m.expense_formatted} · Refunds ${m.refunds_formatted || "₹0.00"}`;

  const surplusEl = document.getElementById("overview-surplus");
  surplusEl.textContent = m.surplus_formatted;
  surplusEl.classList.remove("amount-positive", "amount-negative");
  if (m.surplus_minor > 0) {
    surplusEl.classList.add("amount-positive");
  } else if (m.surplus_minor < 0) {
    surplusEl.classList.add("amount-negative");
  }

  // Mini accounts list
  const acctListEl = document.getElementById("overview-accounts-list");
  acctListEl.replaceChildren();
  for (const acct of (overviewData.accounts_summary || []).slice(0, 6)) {
    const row = document.createElement("div");
    row.className = "overview-mini-row";
    const nameBtn = document.createElement("button");
    nameBtn.type = "button";
    nameBtn.className = "btn-link";
    nameBtn.textContent = acct.name;
    nameBtn.addEventListener("click", () => {
      if (onOpenAccount) onOpenAccount(acct.id);
    });
    const bal = document.createElement("span");
    bal.className = "tabular-nums";
    if (acct.is_liability) {
      bal.textContent =
        acct.outstanding_liability_minor > 0
          ? `${acct.outstanding_liability_formatted} due`
          : acct.credit_balance_surplus_minor > 0
            ? `+${acct.credit_balance_surplus_formatted} credit`
            : "₹0.00";
    } else {
      bal.textContent = acct.balance_formatted;
    }
    row.append(nameBtn, bal);
    acctListEl.appendChild(row);
  }

  // Mini budgets list
  const bListEl = document.getElementById("overview-budgets-list");
  bListEl.replaceChildren();
  const bSummary = overviewData.budget_summary;
  const configuredCats = bSummary?.categories || [];
  if (!bSummary?.overall?.configured && configuredCats.length === 0) {
    const emptyNote = document.createElement("p");
    emptyNote.className = "field-hint";
    emptyNote.textContent = `No monthly budgets set for ${m.label}. Open Budgets to set limits.`;
    bListEl.appendChild(emptyNote);
  } else {
    if (bSummary.overall?.configured) {
      const ovRow = document.createElement("div");
      ovRow.className = "overview-mini-row";
      const lbl = document.createElement("strong");
      lbl.textContent = "Overall Limit";
      const val = document.createElement("span");
      val.className = "tabular-nums";
      val.textContent = `${bSummary.overall.actual_spend_formatted} / ${bSummary.overall.limit_formatted}`;
      ovRow.append(lbl, val);
      bListEl.appendChild(ovRow);
    }
    for (const c of configuredCats.slice(0, 4)) {
      const row = document.createElement("div");
      row.className = "overview-mini-row";
      const lbl = document.createElement("span");
      lbl.textContent = c.category_name;
      const val = document.createElement("span");
      val.className = `tabular-nums status-${c.status}`;
      val.textContent = `${c.net_spend_formatted} / ${c.effective_limit_formatted}`;
      row.append(lbl, val);
      bListEl.appendChild(row);
    }
  }

  const emptyBox = document.getElementById("overview-empty");
  const tableWrap = document.getElementById("overview-table-wrap");
  const viewAllBtn = document.getElementById("overview-view-all-btn");
  const tbody = document.getElementById("overview-recent-body");

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
    const dateTd = document.createElement("td");
    dateTd.setAttribute("data-label", "Date");
    dateTd.className = "col-date tabular-nums";
    dateTd.textContent = tx.tx_date;

    const acctTd = document.createElement("td");
    acctTd.setAttribute("data-label", "Account");
    acctTd.textContent = tx.account_name;

    tr.append(
      dateTd,
      makeCategoryCell(tx),
      makeDetailsCell(tx, { compact: true }),
      acctTd,
      makeAmountCell(tx)
    );
    frag.appendChild(tr);
  }
  tbody.appendChild(frag);
}

export function renderTransactionsList(
  listData,
  {
    append = false,
    selectedIds = new Set(),
    onToggleSelect,
    onEdit,
    onRefund,
    onDelete,
    onRestore,
    onPurge,
    onPreviewAttachment,
  } = {}
) {
  const emptyBox = document.getElementById("tx-empty");
  const tableWrap = document.getElementById("tx-table-wrap");
  const tbody = document.getElementById("tx-history-body");
  const countEl = document.getElementById("tx-history-count");
  const loadMoreWrap = document.getElementById("tx-load-more-wrap");

  const items = listData.transactions || [];
  const totalCount = Number(listData.total_count ?? items.length);
  countEl.textContent = `${totalCount} ${totalCount === 1 ? "entry" : "entries"}`;

  if (!append) {
    tbody.replaceChildren();
  }
  if (!append && items.length === 0) {
    emptyBox.hidden = false;
    tableWrap.hidden = true;
    loadMoreWrap.hidden = true;
    return;
  }

  emptyBox.hidden = true;
  tableWrap.hidden = false;

  const frag = document.createDocumentFragment();
  for (const tx of items) {
    const tr = document.createElement("tr");
    tr.dataset.txId = String(tx.id);

    const checkTd = document.createElement("td");
    checkTd.className = "col-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selectedIds.has(tx.id);
    cb.setAttribute("aria-label", `Select transaction ${tx.merchant || tx.description || tx.id}`);
    cb.addEventListener("change", () => {
      if (onToggleSelect) onToggleSelect(tx.id, cb.checked);
    });
    checkTd.appendChild(cb);

    const dateTd = document.createElement("td");
    dateTd.setAttribute("data-label", "Date");
    dateTd.className = "col-date tabular-nums";
    dateTd.textContent = tx.tx_date;

    const acctTd = document.createElement("td");
    acctTd.setAttribute("data-label", "Account");
    acctTd.textContent = tx.account_name;

    const actTd = document.createElement("td");
    actTd.className = "col-actions";
    const actions = document.createElement("div");
    actions.className = "row-actions";

    if (tx.deleted_at) {
      actions.appendChild(
        makeActionBtn("rotate-ccw", "Restore transaction", () => onRestore && onRestore(tx))
      );
      actions.appendChild(
        makeActionBtn("trash-2", "Delete permanently", () => onPurge && onPurge(tx))
      );
    } else {
      actions.appendChild(
        makeActionBtn("pencil", "Edit transaction", () => onEdit && onEdit(tx))
      );
      if (tx.entry_type === "expense") {
        actions.appendChild(
          makeActionBtn("undo-2", "Record refund", () => onRefund && onRefund(tx))
        );
      }
      actions.appendChild(
        makeActionBtn("trash-2", "Delete transaction", () => onDelete && onDelete(tx))
      );
    }
    actTd.appendChild(actions);

    tr.append(
      checkTd,
      dateTd,
      makeCategoryCell(tx),
      makeDetailsCell(tx, { onPreviewAttachment }),
      makeTypeCell(tx),
      acctTd,
      makeAmountCell(tx),
      actTd
    );
    frag.appendChild(tr);
  }
  tbody.appendChild(frag);
  loadMoreWrap.hidden = tbody.children.length >= totalCount;
}

export function renderAccountsView(
  accountsData,
  selectedAccountId,
  detailData,
  { onSelectAccount, onEditAccount, onTransferFrom, onArchiveAccount, onRestoreAccount } = {}
) {
  const summary = accountsData.summary || {};
  document.getElementById("accounts-net-worth").textContent = summary.net_worth_formatted || "₹0.00";
  document.getElementById("accounts-total-assets").textContent =
    summary.total_assets_formatted || "₹0.00";
  document.getElementById("accounts-total-liabilities").textContent =
    summary.total_liabilities_formatted || "₹0.00";
  document.getElementById("accounts-surplus-credit-meta").textContent =
    summary.total_credit_surplus_minor > 0
      ? `Overpayment credit: ${summary.total_credit_surplus_formatted}`
      : "Outstanding card debt";

  const assetsListEl = document.getElementById("accounts-assets-list");
  const cardsListEl = document.getElementById("accounts-cards-list");
  assetsListEl.replaceChildren();
  cardsListEl.replaceChildren();

  const accounts = accountsData.accounts || [];
  const assetAccounts = accounts.filter((a) => !a.is_liability);
  const cardAccounts = accounts.filter((a) => a.is_liability);

  const renderGroup = (container, list, emptyMsg) => {
    if (list.length === 0) {
      const p = document.createElement("p");
      p.className = "field-hint";
      p.style.padding = "14px";
      p.textContent = emptyMsg;
      container.appendChild(p);
      return;
    }
    for (const acct of list) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "account-row-btn";
      if (acct.id === selectedAccountId) {
        btn.setAttribute("aria-current", "true");
      }

      const left = document.createElement("div");
      const title = document.createElement("div");
      title.className = "account-row-title";
      title.textContent = acct.is_archived ? `${acct.name} (Archived)` : acct.name;
      const meta = document.createElement("div");
      meta.className = "account-row-meta";
      if (acct.is_liability) {
        meta.textContent = acct.credit_limit_formatted
          ? `Limit ${acct.credit_limit_formatted} · Available ${acct.available_credit_formatted}`
          : "Credit card (no limit set)";
      } else {
        meta.textContent = `${acct.account_type_label} · ${acct.active_transaction_count} entries`;
      }
      left.append(title, meta);

      const right = document.createElement("div");
      right.className = "tabular-nums";
      if (acct.is_liability) {
        if (acct.credit_balance_surplus_minor > 0) {
          right.className = "tabular-nums amount-positive";
          right.textContent = `+${acct.credit_balance_surplus_formatted}`;
        } else {
          right.className =
            acct.outstanding_liability_minor > 0
              ? "tabular-nums amount-negative"
              : "tabular-nums";
          right.textContent = acct.outstanding_liability_formatted;
        }
      } else {
        if (acct.negative_balance_warning) {
          right.className = "tabular-nums amount-negative";
        }
        right.textContent = acct.balance_formatted;
      }

      btn.append(left, right);
      btn.addEventListener("click", () => onSelectAccount && onSelectAccount(acct.id));
      container.appendChild(btn);
    }
  };

  renderGroup(assetsListEl, assetAccounts, "No active asset accounts.");
  renderGroup(cardsListEl, cardAccounts, "No credit cards added yet.");

  // Render Account Detail Panel
  const detailPanel = document.getElementById("account-detail-panel");
  detailPanel.replaceChildren();
  if (!detailData || !detailData.account) {
    const empty = document.createElement("p");
    empty.className = "field-hint";
    empty.textContent = "Select an account to view details, activity, and actions.";
    detailPanel.appendChild(empty);
    return;
  }

  const acct = detailData.account;
  const act = detailData.activity;

  const head = document.createElement("div");
  head.className = "section-header";
  const hTitle = document.createElement("h3");
  hTitle.className = "section-title";
  hTitle.textContent = acct.name;
  const badge = document.createElement("span");
  badge.className = "section-meta";
  badge.textContent = acct.account_type_label;
  head.append(hTitle, badge);
  detailPanel.appendChild(head);

  const bigBal = document.createElement("div");
  bigBal.className = "balance-figure tabular-nums";
  bigBal.textContent = acct.is_liability
    ? acct.credit_balance_surplus_minor > 0
      ? `+${acct.credit_balance_surplus_formatted} credit`
      : `${acct.outstanding_liability_formatted} owed`
    : acct.balance_formatted;
  detailPanel.appendChild(bigBal);

  if (acct.negative_balance_warning) {
    const warn = document.createElement("p");
    warn.className = "field-error";
    warn.hidden = false;
    warn.textContent = "Negative recorded balance (check opening balance or prior entries).";
    detailPanel.appendChild(warn);
  }
  if (acct.description) {
    const desc = document.createElement("p");
    desc.className = "field-hint";
    desc.textContent = acct.description;
    detailPanel.appendChild(desc);
  }

  const stats = document.createElement("div");
  stats.className = "detail-stat-grid";
  const statPairs = [
    ["Opening Balance", `${acct.opening_balance_formatted} (${acct.opening_balance_date})`],
    ["Recorded Income", act.income_formatted],
    ["Net Expenses", act.net_expense_formatted],
    ["Net Transfers", act.net_transfer_formatted],
  ];
  if (acct.is_liability && acct.credit_limit_formatted) {
    statPairs.push(["Credit Limit", acct.credit_limit_formatted]);
    statPairs.push([
      "Available / Util",
      `${acct.available_credit_formatted} (${acct.utilization_percent ?? 0}%)`,
    ]);
  }
  for (const [k, v] of statPairs) {
    const block = document.createElement("div");
    const lbl = document.createElement("div");
    lbl.className = "metric-label";
    lbl.textContent = k;
    const val = document.createElement("div");
    val.className = "tabular-nums";
    val.textContent = v;
    block.append(lbl, val);
    stats.appendChild(block);
  }
  detailPanel.appendChild(stats);

  const actionRow = document.createElement("div");
  actionRow.className = "section-actions";
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-secondary btn-sm";
  editBtn.textContent = "Edit Account";
  editBtn.addEventListener("click", () => onEditAccount && onEditAccount(acct));
  actionRow.appendChild(editBtn);

  if (!acct.is_archived) {
    const xferBtn = document.createElement("button");
    xferBtn.type = "button";
    xferBtn.className = "btn btn-secondary btn-sm";
    xferBtn.textContent = acct.is_liability ? "Pay Card" : "Transfer";
    xferBtn.addEventListener("click", () => onTransferFrom && onTransferFrom(acct));
    actionRow.appendChild(xferBtn);

    const archBtn = document.createElement("button");
    archBtn.type = "button";
    archBtn.className = "btn btn-destructive btn-sm";
    archBtn.textContent = "Archive";
    archBtn.addEventListener("click", () => onArchiveAccount && onArchiveAccount(acct));
    actionRow.appendChild(archBtn);
  } else {
    const restBtn = document.createElement("button");
    restBtn.type = "button";
    restBtn.className = "btn btn-primary btn-sm";
    restBtn.textContent = "Restore Account";
    restBtn.addEventListener("click", () => onRestoreAccount && onRestoreAccount(acct));
    actionRow.appendChild(restBtn);
  }
  detailPanel.appendChild(actionRow);

  const recHeader = document.createElement("h4");
  recHeader.className = "metric-label";
  recHeader.style.marginTop = "16px";
  recHeader.style.marginBottom = "8px";
  recHeader.textContent = "Recent Account Entries";
  detailPanel.appendChild(recHeader);

  const recList = document.createElement("div");
  recList.className = "overview-mini-list";
  const recTxs = detailData.recent_transactions || [];
  if (recTxs.length === 0) {
    const none = document.createElement("p");
    none.className = "field-hint";
    none.textContent = "No entries recorded for this account yet.";
    recList.appendChild(none);
  } else {
    for (const tx of recTxs.slice(0, 8)) {
      const row = document.createElement("div");
      row.className = "overview-mini-row";
      const left = document.createElement("span");
      left.textContent = `${tx.tx_date} · ${tx.merchant || tx.description || tx.category_name}`;
      const right = document.createElement("span");
      right.className = "tabular-nums";
      right.textContent = tx.signed_amount_formatted;
      row.append(left, right);
      recList.appendChild(row);
    }
  }
  detailPanel.appendChild(recList);
}

export function renderBudgetsView(budgetData, { onEditCategoryBudget } = {}) {
  const ov = budgetData.overall;
  document.getElementById("budgets-month-label").textContent = budgetData.month_label;
  document.getElementById("budgets-overall-limit").textContent = ov.configured
    ? ov.limit_formatted
    : "Not set";
  document.getElementById("budgets-overall-status").textContent = ov.configured
    ? `${ov.status_label}${ov.usage_percent !== null ? ` (${ov.usage_percent}%)` : ""}`
    : "Independent of category allocations";
  document.getElementById("budgets-allocated-total").textContent = ov.total_allocated_formatted;
  document.getElementById("budgets-allocated-effective").textContent =
    `With rollover: ${ov.total_effective_allocated_formatted}`;
  document.getElementById("budgets-actual-spend").textContent = ov.actual_spend_formatted;
  document.getElementById("budgets-unbudgeted-spend").textContent =
    `Unbudgeted categories: ${ov.unbudgeted_spend_formatted}`;
  document.getElementById("budgets-overall-remaining").textContent = ov.configured
    ? ov.remaining_formatted
    : "—";
  document.getElementById("budgets-configured-meta").textContent =
    `${budgetData.summary.configured_categories} configured`;

  const mismatchBanner = document.getElementById("budgets-mismatch-banner");
  const mismatchText = document.getElementById("budgets-mismatch-text");
  if (ov.allocation_exceeds_overall) {
    mismatchText.textContent =
      `Allocated category budgets (${ov.total_allocated_formatted}) exceed your overall limit ` +
      `(${ov.limit_formatted}) by ${ov.allocation_gap_formatted}.`;
    mismatchBanner.hidden = false;
  } else {
    mismatchBanner.hidden = true;
  }

  const tbody = document.getElementById("budgets-table-body");
  tbody.replaceChildren();
  for (const rowData of budgetData.categories || []) {
    const tr = document.createElement("tr");

    const catTd = makeCategoryCell({
      category_icon: rowData.category_icon,
      category_name: rowData.category_name,
    });

    const baseTd = document.createElement("td");
    baseTd.className = "col-amount tabular-nums";
    baseTd.textContent = rowData.base_limit_formatted ?? "Not set";

    const rollTd = document.createElement("td");
    rollTd.className = "col-amount tabular-nums";
    rollTd.textContent = rowData.rollover_enabled ? `+${rowData.carry_in_formatted}` : "Off";

    const effTd = document.createElement("td");
    effTd.className = "col-amount tabular-nums";
    effTd.textContent = rowData.effective_limit_formatted ?? "—";

    const spendTd = document.createElement("td");
    spendTd.className = "col-amount tabular-nums";
    spendTd.textContent = rowData.net_spend_formatted;

    const remTd = document.createElement("td");
    remTd.className = "col-amount tabular-nums";
    if (rowData.remaining_minor === null) {
      remTd.textContent = "—";
    } else if (rowData.remaining_minor < 0) {
      remTd.className = "col-amount tabular-nums amount-negative";
      remTd.textContent = `${rowData.exceeded_formatted} over`;
    } else {
      remTd.textContent = rowData.remaining_formatted;
    }

    const statusTd = document.createElement("td");
    const statusWrap = document.createElement("div");
    const statusSpan = document.createElement("span");
    statusSpan.className = `status-pill status-${rowData.status}`;
    const iconName =
      rowData.status === "exceeded" || rowData.status === "approaching"
        ? "alert-circle"
        : rowData.status === "on_track" || rowData.status === "reached"
          ? "check-circle-2"
          : "circle-ellipsis";
    statusSpan.appendChild(makeIcon(iconName, "icon-sm"));
    const lbl = document.createElement("span");
    lbl.textContent =
      rowData.usage_percent !== null
        ? `${rowData.status_label} (${rowData.usage_percent}%)`
        : rowData.status_label;
    statusSpan.appendChild(lbl);
    statusWrap.appendChild(statusSpan);

    if (rowData.effective_limit_minor !== null && rowData.effective_limit_minor > 0) {
      const prog = document.createElement("progress");
      prog.className = `finora-progress ${
        rowData.status === "exceeded"
          ? "is-exceeded"
          : rowData.status === "approaching"
            ? "is-approaching"
            : ""
      }`.trim();
      prog.max = 100;
      prog.value = Math.min(100, Math.max(0, Math.round(rowData.usage_percent || 0)));
      prog.setAttribute("aria-label", `${rowData.category_name} budget usage`);
      statusWrap.appendChild(prog);
    }
    statusTd.appendChild(statusWrap);

    const actTd = document.createElement("td");
    actTd.className = "col-actions";
    if (!rowData.category_is_archived) {
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn-secondary btn-sm";
      editBtn.textContent = rowData.base_limit_minor === null ? "Set Limit" : "Edit";
      editBtn.addEventListener("click", () => onEditCategoryBudget && onEditCategoryBudget(rowData));
      actTd.appendChild(editBtn);
    }

    tr.append(catTd, baseTd, rollTd, effTd, spendTd, remTd, statusTd, actTd);
    tbody.appendChild(tr);
  }
}

export function renderSettings(settingsData) {
  const appearance = settingsData.appearance || "system";
  for (const radio of document.querySelectorAll('input[name="appearance"]')) {
    radio.checked = radio.value === appearance;
  }
  document.getElementById("settings-currency").textContent = `${settingsData.currency || "INR"} (₹)`;
  document.getElementById("settings-data-dir").textContent = settingsData.storage?.data_dir || "—";
  document.getElementById("settings-db-path").textContent =
    settingsData.storage?.database_path || settingsData.storage?.db_path || "—";
  document.getElementById("settings-encryption-note").textContent =
    settingsData.storage?.encryption_note || "—";
  document.getElementById("settings-version").textContent = settingsData.version || "0.1.0";
}

export function renderSettingsCategories(
  categories,
  { onEdit, onArchive, onRestore } = {}
) {
  const tbody = document.getElementById("settings-categories-body");
  tbody.replaceChildren();
  for (const cat of categories) {
    const tr = document.createElement("tr");
    const nameTd = makeCategoryCell({
      category_icon: cat.icon,
      category_name: cat.is_archived ? `${cat.name} (Archived)` : cat.name,
    });
    const kindTd = document.createElement("td");
    kindTd.textContent = cat.kind === "income" ? "Income" : "Expense";
    const originTd = document.createElement("td");
    originTd.textContent = cat.is_system ? "Predefined" : "Custom";
    const countTd = document.createElement("td");
    countTd.className = "col-amount tabular-nums";
    countTd.textContent = String(cat.transaction_count ?? 0);

    const actTd = document.createElement("td");
    actTd.className = "col-actions";
    const wrap = document.createElement("div");
    wrap.className = "row-actions";
    wrap.appendChild(makeActionBtn("pencil", "Edit category", () => onEdit && onEdit(cat)));
    if (cat.is_archived) {
      wrap.appendChild(
        makeActionBtn("archive-restore", "Restore category", () => onRestore && onRestore(cat))
      );
    } else {
      wrap.appendChild(
        makeActionBtn("archive", "Archive category", () => onArchive && onArchive(cat))
      );
    }
    actTd.appendChild(wrap);
    tr.append(nameTd, kindTd, originTd, countTd, actTd);
    tbody.appendChild(tr);
  }
}

export function renderSettingsTags(tags, { onRename, onDelete } = {}) {
  const tbody = document.getElementById("settings-tags-body");
  tbody.replaceChildren();
  if (!tags || tags.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.className = "field-hint";
    td.textContent = "No tags created yet. Add a tag above or while recording a transaction.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const tag of tags) {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = `#${tag.name}`;
    const countTd = document.createElement("td");
    countTd.className = "col-amount tabular-nums";
    countTd.textContent = String(tag.transaction_count ?? 0);
    const actTd = document.createElement("td");
    actTd.className = "col-actions";
    const wrap = document.createElement("div");
    wrap.className = "row-actions";
    wrap.appendChild(makeActionBtn("pencil", "Rename tag", () => onRename && onRename(tag)));
    wrap.appendChild(makeActionBtn("trash-2", "Delete tag", () => onDelete && onDelete(tag)));
    actTd.appendChild(wrap);
    tr.append(nameTd, countTd, actTd);
    tbody.appendChild(tr);
  }
}
