/**
 * Accessible native <dialog> workflow for creating Phase 1 transactions.
 */

import { ApiError, api } from "./api.js";

const AMOUNT_INPUT_RE = /^(?:\d{1,12}|(?:\d{1,3}(?:,\d{3})+)|(?:\d{1,2}(?:,\d{2})*,\d{3}))(?:\.\d{1,2})?$/;

function localTodayIso() {
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

export function initTransactionDialog({ getLookups, onSaved }) {
  const dialog = document.getElementById("tx-dialog");
  const form = document.getElementById("tx-form");
  const closeBtn = document.getElementById("tx-dialog-close");
  const cancelBtn = document.getElementById("tx-cancel-btn");
  const submitBtn = document.getElementById("tx-submit-btn");

  const typeRadios = form.querySelectorAll('input[name="entry_type"]');
  const amountWrap = document.getElementById("tx-amount-wrap");
  const amountInput = document.getElementById("tx-amount");
  const categorySelect = document.getElementById("tx-category");
  const accountSelect = document.getElementById("tx-account");
  const dateInput = document.getElementById("tx-date");
  const descInput = document.getElementById("tx-description");
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

  let submissionKey = generateSubmissionKey();
  let isSubmitting = false;

  function setFieldError(name, message) {
    const entry = fieldErrors[name];
    if (!entry) {
      return;
    }
    if (message) {
      entry.text.textContent = message;
      entry.el.hidden = false;
      entry.control.setAttribute("aria-invalid", "true");
      if (entry.wrap) {
        entry.wrap.classList.add("is-invalid");
      }
    } else {
      entry.text.textContent = "";
      entry.el.hidden = true;
      entry.control.removeAttribute("aria-invalid");
      if (entry.wrap) {
        entry.wrap.classList.remove("is-invalid");
      }
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
    for (const radio of typeRadios) {
      if (radio.checked) {
        return radio.value;
      }
    }
    return "expense";
  }

  function populateCategories(kind, preferredCategoryId = null) {
    const { categories } = getLookups();
    const filtered = (categories || []).filter((c) => c.kind === kind);
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

  function populateAccounts() {
    const { accounts } = getLookups();
    accountSelect.replaceChildren();
    for (const acct of accounts || []) {
      const opt = document.createElement("option");
      opt.value = String(acct.id);
      opt.textContent = acct.name;
      if (acct.is_default) {
        opt.selected = true;
      }
      accountSelect.appendChild(opt);
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

  function open() {
    clearAllErrors();
    form.reset();
    for (const radio of typeRadios) {
      radio.checked = radio.value === "expense";
    }
    populateAccounts();
    populateCategories("expense");
    dateInput.value = localTodayIso();
    submissionKey = generateSubmissionKey();
    submitBtn.disabled = false;
    submitBtn.textContent = "Save Transaction";
    dialog.returnValue = "";
    if (!dialog.open) {
      dialog.showModal();
    }
    amountInput.focus();
  }

  function closeDialog(reason = "cancel") {
    if (dialog.open) {
      dialog.close(reason);
    }
  }

  // Fallback light-dismiss outside pointer check for WebKit (where closedby="any" is unsupported)
  let pressedOutside = false;
  const isOutsideDialog = (e) => {
    const rect = dialog.getBoundingClientRect();
    return (
      e.clientX < rect.left ||
      e.clientX > rect.right ||
      e.clientY < rect.top ||
      e.clientY > rect.bottom
    );
  };
  dialog.addEventListener("pointerdown", (e) => {
    pressedOutside = isOutsideDialog(e);
  });
  dialog.addEventListener("pointerup", (e) => {
    if (pressedOutside && isOutsideDialog(e) && !isSubmitting) {
      closeDialog("backdrop");
    }
    pressedOutside = false;
  });

  dialog.addEventListener("close", () => {
    dialog.returnValue = "";
  });

  closeBtn.addEventListener("click", () => closeDialog("close-button"));
  cancelBtn.addEventListener("click", () => closeDialog("cancel"));

  for (const radio of typeRadios) {
    radio.addEventListener("change", () => {
      if (radio.checked) {
        populateCategories(radio.value);
        setFieldError("category_id", "");
      }
    });
  }

  amountInput.addEventListener("blur", () => {
    if (amountInput.value.trim() !== "") {
      validateAmountField();
    }
  });
  amountInput.addEventListener("input", () => setFieldError("amount", ""));
  dateInput.addEventListener("blur", validateDateField);
  dateInput.addEventListener("input", () => setFieldError("tx_date", ""));
  categorySelect.addEventListener("change", () => setFieldError("category_id", ""));
  descInput.addEventListener("input", () => setFieldError("description", ""));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSubmitting) {
      return;
    }
    clearAllErrors();

    const okAmount = validateAmountField();
    const okDate = validateDateField();
    const categoryId = Number(categorySelect.value);
    const accountId = Number(accountSelect.value);

    if (!okAmount) {
      amountInput.focus();
      return;
    }
    if (!Number.isInteger(categoryId) || categoryId <= 0) {
      setFieldError("category_id", "Select a category.");
      categorySelect.focus();
      return;
    }
    if (!okDate) {
      dateInput.focus();
      return;
    }

    isSubmitting = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    try {
      const payload = {
        entry_type: selectedEntryType(),
        account_id: accountId,
        category_id: categoryId,
        amount: amountInput.value.trim(),
        tx_date: dateInput.value.trim(),
        description: descInput.value,
        idempotency_key: submissionKey,
      };
      const result = await api.createTransaction(payload);
      closeDialog("saved");
      await onSaved(result.transaction);
    } catch (err) {
      if (err instanceof ApiError && err.field && fieldErrors[err.field]) {
        setFieldError(err.field, err.message);
        fieldErrors[err.field].control.focus();
      } else {
        formErrorText.textContent =
          err instanceof Error ? err.message : "Could not save transaction. Please try again.";
        formErrorBanner.hidden = false;
      }
    } finally {
      isSubmitting = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Save Transaction";
    }
  });

  return { open, close: closeDialog };
}
