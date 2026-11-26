/* Phase 3 Frontend Integration: Reports (Chart.js), Goals, Recurring, Calendar, Insights & Demo Badge */
import { requestJson as apiFetch } from "./api.js";

const charts = {};
let calMonth = new Date().toISOString().slice(0, 7);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      delete charts[key];
    }
  }

  async function loadReports() {
    const presetEl = document.getElementById("reports-preset");
    const preset = presetEl ? presetEl.value : "current_month";
    const data = await apiFetch("/api/analytics/report?preset=" + encodeURIComponent(preset));

    const sumRow = document.getElementById("reports-summary-row");
    if (sumRow) {
      sumRow.replaceChildren(
        el("span", "summary-chip", "Income: " + data.summary.income_formatted),
        el("span", "summary-chip", "Net Spend: " + data.summary.net_expense_formatted),
        el("span", "summary-chip", "Surplus: " + data.summary.surplus_formatted),
        el(
          "span",
          "summary-chip",
          "Savings Rate: " +
            (data.summary.savings_rate_available ? data.summary.savings_rate_percent + "%" : "Unavailable")
        )
      );
    }

    if (typeof window.Chart === "function") {
      destroyChart("ie");
      const ieCtx = document.getElementById("chart-income-expense");
      if (ieCtx) {
        charts.ie = new window.Chart(ieCtx, {
          type: "bar",
          data: {
            labels: data.monthly_series.map((m) => m.month),
            datasets: [
              { label: "Income", data: data.monthly_series.map((m) => m.income_minor / 100), backgroundColor: "#2e6f40" },
              { label: "Net Expense", data: data.monthly_series.map((m) => m.net_expense_minor / 100), backgroundColor: "#b45309" },
            ],
          },
          options: { responsive: true, maintainAspectRatio: false },
        });
      }

      destroyChart("cat");
      const catCtx = document.getElementById("chart-categories");
      const elig = data.categories.filter((c) => c.doughnut_eligible);
      if (catCtx && elig.length > 0) {
        charts.cat = new window.Chart(catCtx, {
          type: "doughnut",
          data: {
            labels: elig.map((c) => c.category_name),
            datasets: [{ data: elig.map((c) => c.gross_minor / 100) }],
          },
          options: { responsive: true, maintainAspectRatio: false },
        });
      }

      destroyChart("nw");
      const nwCtx = document.getElementById("chart-net-worth");
      if (nwCtx) {
        charts.nw = new window.Chart(nwCtx, {
          type: "line",
          data: {
            labels: data.balance_history.map((b) => b.month),
            datasets: [{ label: "Net Worth", data: data.balance_history.map((b) => b.net_worth_minor / 100), borderColor: "#2e6f40" }],
          },
          options: { responsive: true, maintainAspectRatio: false },
        });
      }
    }

    const merchBox = document.getElementById("reports-merchants-list");
    if (merchBox) {
      merchBox.replaceChildren(
        ...data.merchants.map((m) =>
          el("div", "list-row", m.merchant + " — " + m.net_spend_formatted + " (" + m.tx_count + ")")
        )
      );
    }
  }

  async function loadGoals() {
    const data = await apiFetch("/api/goals");
    const sumEl = document.getElementById("goals-summary-text");
    if (sumEl) {
      sumEl.textContent = "Allocated " + data.summary.total_allocated_formatted + " of " + data.summary.total_target_formatted;
    }
    const box = document.getElementById("goals-list-container");
    if (box) {
      box.replaceChildren(
        ...data.goals.map((g) => {
          const row = el("div", "panel-box");
          row.appendChild(el("strong", "", g.name + " (" + g.progress_percent + "%)"));
          row.appendChild(el("div", "muted-text", g.allocated_formatted + " / " + g.target_formatted));
          return row;
        })
      );
    }
  }

  async function loadRecurring() {
    const data = await apiFetch("/api/recurring");
    const sumEl = document.getElementById("recurring-sub-summary");
    if (sumEl) {
      sumEl.textContent =
        "Est. Monthly Subscriptions: " +
        data.subscription_summary.estimated_monthly_formatted +
        " (" +
        data.subscription_summary.estimated_annual_formatted +
        "/yr)";
    }
    const occBox = document.getElementById("recurring-occurrences-list");
    if (occBox) {
      occBox.replaceChildren(
        ...data.occurrences.slice(0, 15).map((o) =>
          el("div", "panel-box", o.scheduled_date + " · " + o.rule_name + " · " + o.amount_formatted + " [" + o.status + "]")
        )
      );
    }
    const ruleBox = document.getElementById("recurring-rules-list");
    if (ruleBox) {
      ruleBox.replaceChildren(
        ...data.rules.map((r) =>
          el("div", "panel-box", r.name + " · " + r.frequency + " · " + r.amount_formatted + " (" + r.status + ")")
        )
      );
    }
  }

  async function loadCalendar() {
    const data = await apiFetch("/api/calendar?month=" + encodeURIComponent(calMonth));
    const lbl = document.getElementById("cal-month-label");
    if (lbl) lbl.textContent = data.month;
    const grid = document.getElementById("cal-grid");
    if (grid) {
      grid.replaceChildren(
        ...data.days.map((d) => {
          const cell = el("button", "cal-cell", d.date.slice(8) + " (" + (d.posted_count + d.scheduled_count) + ")");
          cell.type = "button";
          cell.addEventListener("click", () => {
            const det = document.getElementById("cal-day-detail");
            if (det) {
              det.replaceChildren(
                el("strong", "", d.date),
                ...d.posted.map((p) => el("div", "", "Posted: " + p.description + " " + p.amount_formatted)),
                ...d.scheduled.map((s) => el("div", "", "Scheduled: " + s.name + " " + s.amount_formatted))
              );
            }
          });
          return cell;
        })
      );
    }
  }

  async function loadInsights() {
    const data = await apiFetch("/api/insights");
    const badge = document.getElementById("nav-unread-badge");
    if (badge) {
      badge.textContent = String(data.unread_count);
      badge.hidden = data.unread_count === 0;
    }
    const lbl = document.getElementById("insights-unread-label");
    if (lbl) lbl.textContent = data.unread_count + " unread insights";
    const box = document.getElementById("insights-list");
    if (box) {
      box.replaceChildren(
        ...data.notifications.map((n) => {
          const card = el("div", "panel-box");
          card.appendChild(el("strong", "", n.title));
          card.appendChild(el("div", "", n.message));
          return card;
        })
      );
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const presetEl = document.getElementById("reports-preset");
    if (presetEl) presetEl.addEventListener("change", loadReports);

    document.querySelectorAll("[data-nav-view]").forEach((link) => {
      link.addEventListener("click", () => {
        const v = link.getAttribute("data-nav-view");
        if (v === "reports") loadReports();
        if (v === "goals") loadGoals();
        if (v === "recurring") loadRecurring();
        if (v === "calendar") loadCalendar();
        if (v === "insights") loadInsights();
      });
    });

    const prevBtn = document.getElementById("cal-prev-btn");
    const nextBtn = document.getElementById("cal-next-btn");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        const dt = new Date(calMonth + "-01T00:00:00");
        dt.setMonth(dt.getMonth() - 1);
        calMonth = dt.toISOString().slice(0, 7);
        loadCalendar();
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        const dt = new Date(calMonth + "-01T00:00:00");
        dt.setMonth(dt.getMonth() + 1);
        calMonth = dt.toISOString().slice(0, 7);
        loadCalendar();
      });
    }

    // Auto-load if directly navigated to a Phase 3 view
    const activeMap = [
      ["view-reports", loadReports],
      ["view-goals", loadGoals],
      ["view-recurring", loadRecurring],
      ["view-calendar", loadCalendar],
      ["view-insights", loadInsights],
    ];
    for (const [id, fn] of activeMap) {
      const sec = document.getElementById(id);
      if (sec && !sec.hidden) {
        fn();
        break;
      }
    }
  });
