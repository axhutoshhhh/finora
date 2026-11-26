"""HTML shell routes served to the native desktop WebView."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from app.services import settings_service

pages_bp = Blueprint("pages", __name__)


_VIEW_TITLES = {
    "overview": "Overview",
    "transactions": "Transactions",
    "accounts": "Accounts",
    "budgets": "Budgets",
    "reports": "Reports",
    "goals": "Savings Goals",
    "recurring": "Recurring Payments",
    "calendar": "Calendar",
    "insights": "Insights",
    "settings": "Settings",
}


def _render_shell(active_view: str) -> str:
    db_path = current_app.config["FINORA_DB_PATH"]
    appearance = settings_service.get_appearance(db_path)
    color_scheme_meta = settings_service.appearance_to_color_scheme_meta(appearance)
    return render_template(
        "app.html",
        active_view=active_view,
        active_title=_VIEW_TITLES.get(active_view, "Overview"),
        appearance=appearance,
        color_scheme_meta=color_scheme_meta,
        app_version=current_app.config["FINORA_APP_VERSION"],
    )


@pages_bp.get("/")
def overview_page() -> str:
    """Render the Finora desktop shell initialized to Overview."""
    return _render_shell("overview")


@pages_bp.get("/transactions")
def transactions_page() -> str:
    """Render the Finora desktop shell initialized to Transactions."""
    return _render_shell("transactions")


@pages_bp.get("/accounts")
def accounts_page() -> str:
    """Render the Finora desktop shell initialized to Accounts."""
    return _render_shell("accounts")


@pages_bp.get("/budgets")
def budgets_page() -> str:
    """Render the Finora desktop shell initialized to Budgets."""
    return _render_shell("budgets")


@pages_bp.get("/reports")
def reports_page() -> str:
    """Render the Finora desktop shell initialized to Reports."""
    return _render_shell("reports")


@pages_bp.get("/goals")
def goals_page() -> str:
    """Render the Finora desktop shell initialized to Savings Goals."""
    return _render_shell("goals")


@pages_bp.get("/recurring")
def recurring_page() -> str:
    """Render the Finora desktop shell initialized to Recurring Payments."""
    return _render_shell("recurring")


@pages_bp.get("/calendar")
def calendar_page() -> str:
    """Render the Finora desktop shell initialized to Calendar."""
    return _render_shell("calendar")


@pages_bp.get("/insights")
def insights_page() -> str:
    """Render the Finora desktop shell initialized to Insights."""
    return _render_shell("insights")


@pages_bp.get("/settings")
def settings_page() -> str:
    """Render the Finora desktop shell initialized to Settings."""
    return _render_shell("settings")
