from unittest.mock import MagicMock

from app.capture.datalens_selectors import TAB_STRIP_SELECTORS, first_visible_locator


def test_first_visible_locator_picks_first_chain_with_count():
    page = MagicMock()

    def locator_side_effect(sel: str):
        m = MagicMock()
        if sel == TAB_STRIP_SELECTORS[0]:
            m.count.return_value = 0
        elif sel == TAB_STRIP_SELECTORS[1]:
            m.count.return_value = 3
        else:
            m.count.return_value = 0
        return m

    page.locator.side_effect = locator_side_effect
    sel, loc = first_visible_locator(page, TAB_STRIP_SELECTORS, min_count=1)
    assert sel == TAB_STRIP_SELECTORS[1]
    assert loc is not None
    assert loc.count() == 3
