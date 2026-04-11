from __future__ import annotations

# DataLens / Yandex Cloud datalens: React shell. Prefer stable a11y roles, then data-qa, then class hooks.
# Order matters: first match wins for "primary" tab strip detection.

TAB_STRIP_SELECTORS: tuple[str, ...] = (
    '[role="tablist"] [role="tab"]',
    '[role="tablist"] button',
    '[role="tab"]',
    'button[role="tab"]',
    '[data-qa*="tab"]',
    '[class*="tabs"] button',
    '[class*="Tabs"] [class*="tab"]',
)

# Shell ready: dashboard canvas / root (any one visible is enough to proceed)
SHELL_READY_SELECTORS: tuple[str, ...] = (
    '[data-qa="chart-widget"]',
    '[data-qa="widget"]',
    '[class*="chartkit"]',
    '[class*="Chart"]',
    '[class*="dash-body"]',
    '[class*="DashBody"]',
    "#root",
    "main",
)

# Optional: header nav links (some dashboards use links instead of tabs)
NAV_LINK_SELECTORS: tuple[str, ...] = (
    'header a[href*="tab"]',
    'nav a[href*="widget"]',
    '[class*="navigation"] a',
)


def first_visible_locator(page, selectors: tuple[str, ...], min_count: int = 1):
    """Return (selector_string, locator) for first chain with count >= min_count, else (None, None)."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n >= min_count:
                return sel, loc
        except Exception:
            continue
    return None, None
