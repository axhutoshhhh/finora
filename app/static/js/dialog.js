/**
 * Accessible native <dialog> controllers for Finora Phase 2 workflows.
 */

import { ApiError, api } from "./api.js";
import { makeIcon } from "./render.js";

const AMOUNT_INPUT_RE =
  /^(?:\d{1,12}|(?:\d{1,3}(?:,\d{3})+)|(?:\d{1,2}(?:,\d{2})*,\d{3}))(?:\.\d{1,2})?$/;

export function localTodayIso() {
  const now = new Date();
  const y = String(now.getFullYear());
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function generateSubmissionKey() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `finora-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function parseToPaiseSafe(raw) {
  const txt = String(raw || "").trim();
  if (!txt || !AMOUNT_INPUT_RE.test(txt)) {
    return null;
  }
  const clean = txt.replaceAll(",", "");
  const parts = clean.split(".");
  const rupees = Number.parseInt(parts[0], 10);
  const paiseStr = (parts[1] || "").padEnd(2, "0").slice(0, 2);
  const paise = Number.parseInt(paiseStr || "0", 10);
  return rupees * 100 + paise;
}

function formatPaisePreview(paise) {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const r = Math.floor(abs / 100);
  const p = abs % 100;
  return `${sign}₹${r.toLocaleString("en-IN")}.${String(p).padStart(2, "0")}`;
}

function wireModalDialog(dialog, { canDismiss = () => true, closeBtn, cancelBtn } = {}) {
  let pressedOutside = false;
  const isOutside = (e) => {
    const rect = dialog.getBoundingClientRect();
    return (
      e.clientX < rect.left ||
      e.clientX > rect.right ||
      e.clientY < rect.top ||
      e.clientY > rect.bottom
    );
  };
  dialog.addEventListener("pointerdown", (e) => {
    pressedOutside = isOutside(e);
  });
  dialog.addEventListener("pointerup", (e) => {
    if (pressedOutside && isOutside(e) && canDismiss() && dialog.open) {
      dialog.close("backdrop");
    }
    pressedOutside = false;
  });
  dialog.addEventListener("close", () => {
    dialog.returnValue = "";
  });
  if (closeBtn) {
    closeBtn.addEventListener("click", () => dialog.open && dialog.close("close"));
  }
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => dialog.open && dialog.close("cancel"));
  }
}

export function initConfirmDialog() {
  const dialog = document.getElementById("confirm-dialog");
  const titleEl = document.getElementById("confirm-dialog-title");
  const msgEl = document.getElementById("confirm-dialog-message");
  const okBtn = document.getElementById("confirm-ok-btn");
  wireModalDialog(dialog, {
    closeBtn: document.getElementById("confirm-dialog-close"),
    cancelBtn: document.getElementById("confirm-cancel-btn"),
  });

  let resolver = null;
  okBtn.addEventListener("click", () => {
    if (resolver) {
      const done = resolver;
      resolver = null;
      dialog.close("confirm");
      done(true);
    }
  });
  dialog.addEventListener("close", () => {
    if (resolver) {
      const done = resolver;
      resolver = null;
      done(false);
    }
  });

  return function askConfirm({ title = "Confirm Action", message, confirmLabel = "Confirm" }) {
    titleEl.textContent = title;
    msgEl.textContent = message;
    okBtn.textContent = confirmLabel;
    if (!dialog.open) {
      dialog.showModal();
    }
    okBtn.focus();
    return new Promise((resolve) => {
      resolver = resolve;
    });
  };
}

export function initAttachmentPreviewDialog() {
  const dialog = document.getElementById("attachment-dialog");
  const titleEl = document.getElementById("attachment-dialog-title");
  const box = document.getElementById("attachment-preview-box");
  const dlLink = document.getElementById("attachment-download-link");
  wireModalDialog(dialog, {
    closeBtn: document.getElementById("attachment-dialog-close"),
    cancelBtn: document.getElementById("attachment-close-btn"),
  });

  return async function previewAttachment(att) {
    titleEl.textContent = att.original_filename || "Receipt Preview";
    box.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "field-hint";
    loading.textContent = "Loading local receipt…";
    box.appendChild(loading);
    if (!dialog.open) {
      dialog.showModal();
    }
    try {
      const blob = await api.fetchAttachmentBlob(att.id);
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Could not read receipt."));
        reader.readAsDataURL(blob);
      });
      dlLink.href = String(dataUrl);
      dlLink.download = att.original_filename || "receipt";
      box.replaceChildren();
      if (att.mime_type === "image/png" || att.mime_type === "image/jpeg") {
        const img = document.createElement("img");
        img.src = String(dataUrl);
        img.alt = att.original_filename || "Receipt image";
        box.appendChild(img);
      } else {
        const note = document.createElement("p");
        note.className = "field-hint";
        note.textContent = `${att.original_filename} (${Math.ceil((att.size_bytes || 0) / 1024)} KiB PDF). Click Download Copy below to open externally.`;
        box.appendChild(note);
      }
    } catch (err) {
      box.replaceChildren();
      const errP = document.createElement("p");
      errP.className = "field-error";
      errP.hidden = false;
      errP.textContent = err instanceof Error ? err.message : "Failed to load receipt.";
      box.appendChild(errP);
    }
  };
}

export function initTransactionDialog({ getLookups, onSaved, onPreviewAttachment }) {
  const dialog = document.getElementById("tx-dialog");
  const titleEl = document.getElementById("tx-dialog-title");
  const form = document.getElementById("tx-form");
  const submitBtn = document.getElementById("tx-submit-btn");
  const typeFieldset = document.getElementById("tx-type-fieldset");
  const typeRadios = form.querySelectorAll('input[name="entry_type"]');
  const amountWrap = document.getElementById("tx-amount-wrap");
  const amountInput = document.getElementById("tx-amount");
  const standardCatBlock = document.getElementById("tx-standard-category-block");
  const categorySelect = document.getElementById("tx-category");
  const splitToggleBtn = document.getElementById("tx-split-toggle-btn");
  const splitBlock = document.getElementById("tx-split-block");
  const splitRowsEl = document.getElementById("tx-split-rows");
  const splitRemainingEl = document.getElementById("tx-split-remaining");
  const splitAddRowBtn = document.getElementById("tx-split-add-row-btn");
  const splitCancelBtn = document.getElementById("tx-split-cancel-btn");
  const singleAccountRow = document.getElementById("tx-single-account-row");
  const accountSelect = document.getElementById("tx-account");
  const paymentMethodSelect = document.getElementById("tx-payment-method");
  const transferAccountsRow = document.getElementById("tx-transfer-accounts-row");
  const fromAccountSelect = document.getElementById("tx-from-account");
  const toAccountSelect = document.getElementById("tx-to-account");
  const dateInput = document.getElementById("tx-date");
  const merchantField = document.getElementById("tx-merchant-field");
  const merchantInput = document.getElementById("tx-merchant");
  const descInput = document.getElementById("tx-description");
  const tagsPicker = document.getElementById("tx-tags-picker");
  const attachmentInput = document.getElementById("tx-attachment-input");
  const existingAttachmentsEl = document.getElementById("tx-existing-attachments");
  const formErrorBanner = document.getElementById("tx-form-error");
  const formErrorText = document.getElementById("tx-form-error-text");

  const fieldErrors = {
    amount: {
      el: document.getElementById("tx-amount-error"),
      text: document.getElementById("tx-amount-error-text"),
      control: amountInput,
      wrap: amountWrap,
    },
    category_id: {
      el: document.getElementById("tx-category-error"),
      text: document.getElementById("tx-category-error-text"),
      control: categorySelect,
    },
    splits: {
      el: document.getElementById("tx-splits-error"),
      text: document.getElementById("tx-splits-error-text"),
      control: splitAddRowBtn,
    },
    tx_date: {
      el: document.getElementById("tx-date-error"),
      text: document.getElementById("tx-date-error-text"),
      control: dateInput,
    },
    description: {
      el: document.getElementById("tx-description-error"),
      text: document.getElementById("tx-description-error-text"),
      control: descInput,
    },
  };

  let isSubmitting = false;
  let submissionKey = generateSubmissionKey();
  let editingTx = null;
  let splitMode = false;

  wireModalDialog(dialog, {
    canDismiss: () => !isSubmitting,
    closeBtn: document.getElementById("tx-dialog-close"),
    cancelBtn: document.getElementById("tx-cancel-btn"),
  });

  function setFieldError(name, message) {
    const entry = fieldErrors[name];
    if (!entry) return;
    if (message) {
      entry.text.textContent = message;
      entry.el.hidden = false;
      entry.control.setAttribute("aria-invalid", "true");
      if (entry.wrap) entry.wrap.classList.add("is-invalid");
    } else {
      entry.text.textContent = "";
      entry.el.hidden = true;
      entry.control.removeAttribute("aria-invalid");
      if (entry.wrap) entry.wrap.classList.remove("is-invalid");
    }
  }

  function clearAllErrors() {
    formErrorBanner.hidden = true;
    formErrorText.textContent = "";
    for (const key of Object.keys(fieldErrors)) {
      setFieldError(key, "");
    }
  }

  function selectedEntryType() {
    if (editingTx && editingTx.entry_type === "refund") {
      return "refund";
    }
    for (const r of typeRadios) {
      if (r.checked) return r.value;
    }
    return "expense";
  }

  function populateAccountSelect(sel, accounts, { excludeCreditCard = false, preferredId = null } = {}) {
    sel.replaceChildren();
    for (const acct of accounts || []) {
      if (excludeCreditCard && acct.account_type === "credit_card") {
        continue;
      }
      const opt = document.createElement("option");
      opt.value = String(acct.id);
      opt.textContent = acct.name;
      if (preferredId !== null && String(acct.id) === String(preferredId)) {
        opt.selected = true;
      } else if (preferredId === null && acct.is_default) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    }
  }

  function populateCategories(kind, preferredCategoryId = null) {
    const { categories } = getLookups();
    const filtered = (categories || []).filter((c) => c.kind === (kind === "income" ? "income" : "expense"));
    categorySelect.replaceChildren();
    for (const cat of filtered) {
      const opt = document.createElement("option");
      opt.value = String(cat.id);
      opt.textContent = cat.name;
      if (preferredCategoryId !== null && String(cat.id) === String(preferredCategoryId)) {
        opt.selected = true;
      }
      categorySelect.appendChild(opt);
    }
  }

  function updateSplitRemaining() {
    const totalPaise = parseToPaiseSafe(amountInput.value);
    let allocated = 0;
    for (const row of splitRowsEl.querySelectorAll(".split-row-item")) {
      const val = parseToPaiseSafe(row.querySelector("input").value);
      if (val !== null) allocated += val;
    }
    if (totalPaise === null) {
      splitRemainingEl.textContent = "Enter total amount first";
    } else {
      splitRemainingEl.textContent = `Remaining: ${formatPaisePreview(totalPaise - allocated)}`;
    }
  }

  function addSplitRow(catId = null, amountStr = "") {
    const kind = selectedEntryType() === "income" ? "income" : "expense";
    const { categories } = getLookups();
    const filtered = (categories || []).filter((c) => c.kind === kind);

    const row = document.createElement("div");
    row.className = "split-row-item";

    const sel = document.createElement("select");
    sel.className = "form-control";
    sel.setAttribute("aria-label", "Split category");
    for (const cat of filtered) {
      const opt = document.createElement("option");
      opt.value = String(cat.id);
      opt.textContent = cat.name;
      if (catId !== null && String(cat.id) === String(catId)) opt.selected = true;
      sel.appendChild(opt);
    }

    const inp = document.createElement("input");
    inp.type = "text";
    inp.inputMode = "decimal";
    inp.className = "form-control tabular-nums";
    inp.placeholder = "0.00";
    inp.value = amountStr;
    inp.setAttribute("aria-label", "Split amount");
    inp.addEventListener("input", () => {
      setFieldError("splits", "");
      updateSplitRemaining();
    });

    const rmBtn = document.createElement("button");
    rmBtn.type = "button";
    rmBtn.className = "btn-icon";
    rmBtn.setAttribute("aria-label", "Remove split row");
    rmBtn.appendChild(makeIcon("x", "icon-sm"));
    rmBtn.addEventListener("click", () => {
      if (splitRowsEl.children.length > 2) {
        row.remove();
        updateSplitRemaining();
      }
    });

    row.append(sel, inp, rmBtn);
    splitRowsEl.appendChild(row);
    updateSplitRemaining();
  }

  function syncModeLayout() {
    const mode = selectedEntryType();
    const isTransfer = mode === "transfer";
    singleAccountRow.hidden = isTransfer;
    transferAccountsRow.hidden = !isTransfer;
    merchantField.hidden = isTransfer;

    if (isTransfer) {
      splitMode = false;
      standardCatBlock.hidden = true;
      splitBlock.hidden = true;
    } else {
      standardCatBlock.hidden = splitMode;
      splitBlock.hidden = !splitMode;
      if (!splitMode) {
        populateCategories(mode);
      }
    }
    splitToggleBtn.hidden = mode === "refund" || isTransfer;
  }

  function populateTagsPicker(selectedTagIds = []) {
    const selectedSet = new Set(selectedTagIds.map(Number));
    const { tags } = getLookups();
    tagsPicker.replaceChildren();
    if (!tags || tags.length === 0) {
      const hint = document.createElement("span");
      hint.className = "field-hint";
      hint.textContent = "No tags yet (manage tags in Settings).";
      tagsPicker.appendChild(hint);
      return;
    }
    for (const t of tags) {
      const lbl = document.createElement("label");
      lbl.className = "tag-check-pill";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = String(t.id);
      cb.checked = selectedSet.has(Number(t.id));
      const span = document.createElement("span");
      span.textContent = `#${t.name}`;
      lbl.append(cb, span);
      tagsPicker.appendChild(lbl);
    }
  }

  function renderExistingAttachments(attachments = []) {
    existingAttachmentsEl.replaceChildren();
    for (const att of attachments) {
      const item = document.createElement("div");
      item.className = "attachment-item";
      const nameWrap = document.createElement("div");
      nameWrap.className = "filename-ellipsis";
      const nameSpan = document.createElement("span");
      nameSpan.textContent = att.original_filename;
      nameWrap.appendChild(nameSpan);

      const act = document.createElement("div");
      act.className = "section-actions";
      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "btn-link btn-sm";
      viewBtn.textContent = "View";
      viewBtn.addEventListener("click", () => onPreviewAttachment && onPreviewAttachment(att));

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-icon";
      delBtn.setAttribute("aria-label", "Remove attachment");
      delBtn.appendChild(makeIcon("trash-2", "icon-sm"));
      delBtn.addEventListener("click", async () => {
        try {
          await api.deleteAttachment(att.id);
          item.remove();
          if (editingTx) {
            editingTx.attachments = (editingTx.attachments || []).filter((a) => a.id !== att.id);
          }
          await onSaved({ updatedQuietly: true });
        } catch (err) {
          formErrorText.textContent = err instanceof Error ? err.message : "Failed to remove attachment.";
          formErrorBanner.hidden = false;
        }
      });
      act.append(viewBtn, delBtn);
      item.append(nameWrap, act);
      existingAttachmentsEl.appendChild(item);
    }
  }

  function validateAmountField() {
    const raw = amountInput.value.trim();
    if (!raw) {
      setFieldError("amount", "Enter a transaction amount.");
      return false;
    }
    if (!AMOUNT_INPUT_RE.test(raw) || Number(raw.replaceAll(",", "")) <= 0) {
      setFieldError(
        "amount",
        "Enter a positive amount with up to two decimal places (e.g. 250.50)."
      );
      return false;
    }
    setFieldError("amount", "");
    return true;
  }

  function validateDateField() {
    const val = dateInput.value.trim();
    if (!val || !/^\d{4}-\d{2}-\d{2}$/.test(val)) {
      setFieldError("tx_date", "Select a valid transaction date.");
      return false;
    }
    setFieldError("tx_date", "");
    return true;
  }

  function open({ mode = "expense", tx = null, defaultFromAccountId = null } = {}) {
    clearAllErrors();
    form.reset();
    attachmentInput.value = "";
    editingTx = tx;
    splitMode = false;
    splitRowsEl.replaceChildren();
    existingAttachmentsEl.replaceChildren();
    submissionKey = generateSubmissionKey();

    const { accounts } = getLookups();
    const initialMode = tx ? tx.entry_type : mode;
    titleEl.textContent = tx
      ? `Edit ${tx.entry_type === "transfer" ? "Transfer" : tx.entry_type === "refund" ? "Refund" : "Transaction"}`
      : "New Transaction";
    submitBtn.textContent = tx ? "Save Changes" : "Save Transaction";
    typeFieldset.hidden = Boolean(tx);

    for (const radio of typeRadios) {
      radio.checked = radio.value === initialMode;
    }

    populateAccountSelect(accountSelect, accounts, {
      preferredId: tx ? tx.account_id : null,
    });
    populateAccountSelect(fromAccountSelect, accounts, {
      excludeCreditCard: true,
      preferredId: tx?.from_account_id ?? defaultFromAccountId,
    });
    const nonSrc = (accounts || []).find(
      (a) => String(a.id) !== String(fromAccountSelect.value)
    );
    populateAccountSelect(toAccountSelect, accounts, {
      preferredId: tx?.to_account_id ?? (nonSrc ? nonSrc.id : null),
    });

    if (tx) {
      amountInput.value = `${Math.floor(tx.amount_minor / 100)}.${String(tx.amount_minor % 100).padStart(2, "0")}`;
      dateInput.value = tx.tx_date;
      merchantInput.value = tx.merchant || "";
      descInput.value = tx.description || "";
      paymentMethodSelect.value = tx.payment_method || "other";
      populateTagsPicker((tx.tags || []).map((t) => t.id));
      renderExistingAttachments(tx.attachments || []);

      if (tx.is_split && tx.entry_type !== "transfer" && tx.entry_type !== "refund") {
        splitMode = true;
        for (const p of tx.postings || []) {
          const amtStr = `${Math.floor(p.amount_minor / 100)}.${String(p.amount_minor % 100).padStart(2, "0")}`;
          addSplitRow(p.category_id, amtStr);
        }
      } else {
        populateCategories(tx.entry_type, tx.category_id);
      }
    } else {
      dateInput.value = localTodayIso();
      paymentMethodSelect.value = "other";
      populateCategories(initialMode);
      populateTagsPicker([]);
    }

    syncModeLayout();
    submitBtn.disabled = false;
    if (!dialog.open) {
      dialog.showModal();
    }
    amountInput.focus();
  }

  splitToggleBtn.addEventListener("click", () => {
    splitMode = true;
    if (splitRowsEl.children.length === 0) {
      const catId = categorySelect.value || null;
      addSplitRow(catId, amountInput.value.trim());
      addSplitRow(null, "");
    }
    syncModeLayout();
  });

  splitCancelBtn.addEventListener("click", () => {
    splitMode = false;
    splitRowsEl.replaceChildren();
    syncModeLayout();
  });

  splitAddRowBtn.addEventListener("click", () => addSplitRow(null, ""));

  for (const radio of typeRadios) {
    radio.addEventListener("change", () => {
      if (radio.checked) {
        splitMode = false;
        splitRowsEl.replaceChildren();
        syncModeLayout();
        setFieldError("category_id", "");
      }
    });
  }

  amountInput.addEventListener("blur", () => {
    if (amountInput.value.trim() !== "") validateAmountField();
  });
  amountInput.addEventListener("input", () => {
    setFieldError("amount", "");
    if (splitMode) updateSplitRemaining();
  });
  dateInput.addEventListener("blur", validateDateField);
  dateInput.addEventListener("input", () => setFieldError("tx_date", ""));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting) return;
    clearAllErrors();

    const mode = selectedEntryType();
    if (!validateAmountField()) {
      amountInput.focus();
      return;
    }
    if (!validateDateField()) {
      dateInput.focus();
      return;
    }

    const selectedTagIds = Array.from(
      tagsPicker.querySelectorAll('input[type="checkbox"]:checked')
    ).map((el) => Number(el.value));

    isSubmitting = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    try {
      let savedTx = null;
      if (mode === "transfer") {
        const xferPayload = {
          from_account_id: Number(fromAccountSelect.value),
          to_account_id: Number(toAccountSelect.value),
          amount: amountInput.value.trim(),
          tx_date: dateInput.value.trim(),
          description: descInput.value,
          tag_ids: selectedTagIds,
        };
        if (editingTx) {
          const res = await api.updateTransaction(editingTx.id, {
            ...xferPayload,
            expected_revision: editingTx.revision,
          });
          savedTx = res.transaction;
        } else {
          const res = await api.createTransfer({
            ...xferPayload,
            idempotency_key: submissionKey,
          });
          savedTx = res.transaction;
        }
      } else {
        const basePayload = {
          account_id: Number(accountSelect.value),
          amount: amountInput.value.trim(),
          tx_date: dateInput.value.trim(),
          merchant: merchantInput.value,
          payment_method: paymentMethodSelect.value,
          description: descInput.value,
          tag_ids: selectedTagIds,
        };

        if (splitMode) {
          basePayload.splits = Array.from(splitRowsEl.querySelectorAll(".split-row-item")).map(
            (r) => ({
              category_id: Number(r.querySelector("select").value),
              amount: r.querySelector("input").value.trim(),
            })
          );
        } else if (mode !== "refund") {
          const catId = Number(categorySelect.value);
          if (!Number.isInteger(catId) || catId <= 0) {
            setFieldError("category_id", "Select a category.");
            categorySelect.focus();
            return;
          }
          basePayload.category_id = catId;
        }

        if (editingTx) {
          const res = await api.updateTransaction(editingTx.id, {
            ...basePayload,
            expected_revision: editingTx.revision,
          });
          savedTx = res.transaction;
        } else {
          const res = await api.createTransaction({
            ...basePayload,
            entry_type: mode,
            idempotency_key: submissionKey,
          });
          savedTx = res.transaction;
        }
      }

      const pendingFile = attachmentInput.files?.[0];
      if (pendingFile && savedTx) {
        const attRes = await api.uploadAttachment(savedTx.id, pendingFile);
        savedTx.attachments = [...(savedTx.attachments || []), attRes.attachment];
      }

      if (dialog.open) dialog.close("saved");
      await onSaved({ transaction: savedTx, edited: Boolean(editingTx) });
    } catch (err) {
      if (err instanceof ApiError && err.field && fieldErrors[err.field]) {
        setFieldError(err.field, err.message);
        fieldErrors[err.field].control.focus();
      } else {
        formErrorText.textContent =
          err instanceof Error ? err.message : "Could not save transaction.";
        formErrorBanner.hidden = false;
      }
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
      submitBtn.textContent = editingTx ? "Save Changes" : "Save Transaction";
    }
  });

  return { open };
}

export function initRefundDialog({ getLookups, onSaved }) {
  const dialog = document.getElementById("refund-dialog");
  const form = document.getElementById("refund-form");
  const errBanner = document.getElementById("refund-form-error");
  const errText = document.getElementById("refund-form-error-text");
  const summaryEl = document.getElementById("refund-parent-summary");
  const amtInput = document.getElementById("refund-amount");
  const allocWrap = document.getElementById("refund-allocations-wrap");
  const acctSelect = document.getElementById("refund-account");
  const dateInput = document.getElementById("refund-date");
  const descInput = document.getElementById("refund-description");
  const submitBtn = document.getElementById("refund-submit-btn");

  let parentTx = null;
  let refundInfo = null;
  let isSubmitting = false;

  wireModalDialog(dialog, {
    canDismiss: () => !isSubmitting,
    closeBtn: document.getElementById("refund-dialog-close"),
    cancelBtn: document.getElementById("refund-cancel-btn"),
  });

  async function open(tx) {
    parentTx = tx;
    errBanner.hidden = true;
    form.reset();
    allocWrap.replaceChildren();
    allocWrap.hidden = true;
    dateInput.value = localTodayIso();

    const { accounts } = getLookups();
    acctSelect.replaceChildren();
    for (const a of accounts || []) {
      const opt = document.createElement("option");
      opt.value = String(a.id);
      opt.textContent = a.name;
      if (a.id === tx.account_id) opt.selected = true;
      acctSelect.appendChild(opt);
    }

    try {
      refundInfo = await api.getRefunds(tx.id);
      summaryEl.textContent =
        `Original: ${refundInfo.original_transaction.amount_formatted} · ` +
        `Remaining refundable: ${refundInfo.remaining_refundable_formatted}`;
      const rem = refundInfo.remaining_refundable_minor;
      amtInput.value = `${Math.floor(rem / 100)}.${String(rem % 100).padStart(2, "0")}`;

      if ((refundInfo.allocations || []).length > 1) {
        allocWrap.hidden = false;
        const h = document.createElement("strong");
        h.className = "form-label";
        h.textContent = "Refund Category Allocations (up to remaining per category)";
        allocWrap.appendChild(h);
        for (const al of refundInfo.allocations) {
          const row = document.createElement("div");
          row.className = "split-row-item";
          const lbl = document.createElement("span");
          lbl.textContent = `${al.category_name} (max ${al.remaining_formatted})`;
          const inp = document.createElement("input");
          inp.type = "text";
          inp.inputMode = "decimal";
          inp.className = "form-control tabular-nums";
          inp.dataset.categoryId = String(al.category_id);
          inp.value = `${Math.floor(al.remaining_minor / 100)}.${String(al.remaining_minor % 100).padStart(2, "0")}`;
          row.append(lbl, inp);
          allocWrap.appendChild(row);
        }
      }
      if (!dialog.open) dialog.showModal();
      amtInput.focus();
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Failed to load refund options.";
      errBanner.hidden = false;
      if (!dialog.open) dialog.showModal();
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting || !parentTx) return;
    errBanner.hidden = true;
    isSubmitting = true;
    submitBtn.disabled = true;

    try {
      const payload = {
        amount: amtInput.value.trim(),
        account_id: Number(acctSelect.value),
        tx_date: dateInput.value.trim(),
        description: descInput.value,
        idempotency_key: generateSubmissionKey(),
      };
      if (!allocWrap.hidden) {
        const allocs = [];
        for (const inp of allocWrap.querySelectorAll("input[data-category-id]")) {
          const v = inp.value.trim();
          if (v && Number(v.replaceAll(",", "")) > 0) {
            allocs.push({ category_id: Number(inp.dataset.categoryId), amount: v });
          }
        }
        payload.allocations = allocs;
      }
      const res = await api.createRefund(parentTx.id, payload);
      if (dialog.open) dialog.close("saved");
      await onSaved(res.transaction);
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Unable to record refund.";
      errBanner.hidden = false;
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
    }
  });

  return { open };
}

export function initAccountDialog({ onSaved }) {
  const dialog = document.getElementById("account-dialog");
  const titleEl = document.getElementById("account-dialog-title");
  const form = document.getElementById("account-form");
  const errBanner = document.getElementById("account-form-error");
  const errText = document.getElementById("account-form-error-text");
  const nameInput = document.getElementById("account-name");
  const typeSelect = document.getElementById("account-type");
  const openingLabel = document.getElementById("account-opening-label");
  const openingInput = document.getElementById("account-opening-balance");
  const dateInput = document.getElementById("account-opening-date");
  const ccFields = document.getElementById("account-cc-fields");
  const limitInput = document.getElementById("account-credit-limit");
  const dirSelect = document.getElementById("account-opening-dir");
  const descInput = document.getElementById("account-description");
  const submitBtn = document.getElementById("account-submit-btn");

  let editingAcct = null;
  let isSubmitting = false;

  wireModalDialog(dialog, {
    canDismiss: () => !isSubmitting,
    closeBtn: document.getElementById("account-dialog-close"),
    cancelBtn: document.getElementById("account-cancel-btn"),
  });

  function syncCreditCardFields() {
    const isCard = typeSelect.value === "credit_card";
    ccFields.hidden = !isCard;
    openingLabel.textContent = isCard
      ? "Opening Card Balance (INR)"
      : "Opening Balance (INR)";
  }

  typeSelect.addEventListener("change", syncCreditCardFields);

  function open(acct = null) {
    editingAcct = acct;
    errBanner.hidden = true;
    form.reset();
    titleEl.textContent = acct ? `Edit ${acct.name}` : "New Financial Account";
    typeSelect.disabled = Boolean(acct && acct.total_posting_count > 0);
    if (acct) {
      nameInput.value = acct.name;
      typeSelect.value = acct.account_type;
      const absOpen = Math.abs(acct.opening_balance_minor);
      openingInput.value = `${Math.floor(absOpen / 100)}.${String(absOpen % 100).padStart(2, "0")}`;
      dateInput.value = acct.opening_balance_date || localTodayIso();
      dirSelect.value = acct.opening_balance_minor > 0 ? "credit" : "debt";
      limitInput.value =
        acct.credit_limit_minor !== null
          ? `${Math.floor(acct.credit_limit_minor / 100)}.${String(acct.credit_limit_minor % 100).padStart(2, "0")}`
          : "";
      descInput.value = acct.description || "";
    } else {
      typeSelect.value = "bank";
      openingInput.value = "0.00";
      dateInput.value = localTodayIso();
      dirSelect.value = "debt";
    }
    syncCreditCardFields();
    if (!dialog.open) dialog.showModal();
    nameInput.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting) return;
    errBanner.hidden = true;
    isSubmitting = true;
    submitBtn.disabled = true;

    try {
      const payload = {
        name: nameInput.value.trim(),
        account_type: typeSelect.value,
        opening_balance: openingInput.value.trim() || "0",
        opening_balance_date: dateInput.value.trim(),
        description: descInput.value,
      };
      if (typeSelect.value === "credit_card") {
        payload.opening_balance_direction = dirSelect.value;
        payload.credit_limit = limitInput.value.trim() || null;
      }
      const res = editingAcct
        ? await api.updateAccount(editingAcct.id, payload)
        : await api.createAccount(payload);
      if (dialog.open) dialog.close("saved");
      await onSaved(res.account);
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Could not save account.";
      errBanner.hidden = false;
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
    }
  });

  return { open };
}

export function initBudgetDialog({ onSaved }) {
  const dialog = document.getElementById("budget-dialog");
  const titleEl = document.getElementById("budget-dialog-title");
  const contextEl = document.getElementById("budget-dialog-context");
  const form = document.getElementById("budget-form");
  const errBanner = document.getElementById("budget-form-error");
  const errText = document.getElementById("budget-form-error-text");
  const limitInput = document.getElementById("budget-limit-input");
  const rolloverRow = document.getElementById("budget-rollover-row");
  const rolloverCb = document.getElementById("budget-rollover-checkbox");
  const removeBtn = document.getElementById("budget-remove-btn");
  const submitBtn = document.getElementById("budget-submit-btn");

  let mode = "category";
  let targetMonth = "";
  let targetCat = null;
  let isSubmitting = false;

  wireModalDialog(dialog, {
    canDismiss: () => !isSubmitting,
    closeBtn: document.getElementById("budget-dialog-close"),
    cancelBtn: document.getElementById("budget-cancel-btn"),
  });

  function openCategory({ month, monthLabel, row }) {
    mode = "category";
    targetMonth = month;
    targetCat = row;
    errBanner.hidden = true;
    titleEl.textContent = `${row.category_name} Budget`;
    contextEl.textContent = `Configure monthly spending limit for ${monthLabel}.`;
    rolloverRow.hidden = false;
    rolloverCb.checked = Boolean(row.rollover_enabled);
    if (row.base_limit_minor !== null) {
      limitInput.value = `${Math.floor(row.base_limit_minor / 100)}.${String(row.base_limit_minor % 100).padStart(2, "0")}`;
      removeBtn.hidden = false;
    } else {
      limitInput.value = "";
      removeBtn.hidden = true;
    }
    if (!dialog.open) dialog.showModal();
    limitInput.focus();
  }

  function openOverall({ month, monthLabel, overall }) {
    mode = "overall";
    targetMonth = month;
    targetCat = null;
    errBanner.hidden = true;
    titleEl.textContent = "Overall Monthly Spending Limit";
    contextEl.textContent = `Independent overall cap across all spending in ${monthLabel}.`;
    rolloverRow.hidden = true;
    if (overall.configured && overall.limit_minor !== null) {
      limitInput.value = `${Math.floor(overall.limit_minor / 100)}.${String(overall.limit_minor % 100).padStart(2, "0")}`;
      removeBtn.hidden = false;
    } else {
      limitInput.value = "";
      removeBtn.hidden = true;
    }
    if (!dialog.open) dialog.showModal();
    limitInput.focus();
  }

  removeBtn.addEventListener("click", async () => {
    if (isSubmitting) return;
    isSubmitting = true;
    try {
      const data =
        mode === "overall"
          ? await api.deleteOverallBudget(targetMonth)
          : await api.deleteCategoryBudget(targetCat.category_id, targetMonth);
      if (dialog.open) dialog.close("removed");
      await onSaved(data);
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Could not remove budget.";
      errBanner.hidden = false;
    } finally {
      isSubmitting = false;
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting) return;
    errBanner.hidden = true;
    isSubmitting = true;
    submitBtn.disabled = true;

    try {
      const data =
        mode === "overall"
          ? await api.setOverallBudget({ month: targetMonth, limit: limitInput.value.trim() })
          : await api.setCategoryBudget({
              month: targetMonth,
              category_id: targetCat.category_id,
              limit: limitInput.value.trim(),
              rollover_enabled: rolloverCb.checked,
            });
      if (dialog.open) dialog.close("saved");
      await onSaved(data);
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Could not save budget.";
      errBanner.hidden = false;
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
    }
  });

  return { openCategory, openOverall };
}

export function initCategoryDialog({ onSaved }) {
  const dialog = document.getElementById("category-dialog");
  const titleEl = document.getElementById("category-dialog-title");
  const form = document.getElementById("category-form");
  const errBanner = document.getElementById("category-form-error");
  const errText = document.getElementById("category-form-error-text");
  const nameInput = document.getElementById("category-name-input");
  const kindSelect = document.getElementById("category-kind-select");
  const iconSelect = document.getElementById("category-icon-select");
  const submitBtn = document.getElementById("category-submit-btn");

  let editingCat = null;
  let isSubmitting = false;

  wireModalDialog(dialog, {
    canDismiss: () => !isSubmitting,
    closeBtn: document.getElementById("category-dialog-close"),
    cancelBtn: document.getElementById("category-cancel-btn"),
  });

  function open(cat = null) {
    editingCat = cat;
    errBanner.hidden = true;
    form.reset();
    titleEl.textContent = cat ? `Edit ${cat.name}` : "New Category";
    kindSelect.disabled = Boolean(cat);
    if (cat) {
      nameInput.value = cat.name;
      kindSelect.value = cat.kind;
      iconSelect.value = cat.icon || "circle-ellipsis";
    } else {
      kindSelect.value = "expense";
      iconSelect.value = "tag";
    }
    if (!dialog.open) dialog.showModal();
    nameInput.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting) return;
    errBanner.hidden = true;
    isSubmitting = true;
    submitBtn.disabled = true;

    try {
      if (editingCat) {
        await api.updateCategory(editingCat.id, {
          name: nameInput.value.trim(),
          icon: iconSelect.value,
        });
      } else {
        await api.createCategory({
          name: nameInput.value.trim(),
          kind: kindSelect.value,
          icon: iconSelect.value,
        });
      }
      if (dialog.open) dialog.close("saved");
      await onSaved();
    } catch (err) {
      errText.textContent = err instanceof Error ? err.message : "Could not save category.";
      errBanner.hidden = false;
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
    }
  });

  return { open };
}
