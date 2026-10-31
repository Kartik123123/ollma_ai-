"""Extracts a compact, LLM-friendly list of the interactive elements
currently visible on the page.

Visibility filtering happens INSIDE the browser via one JavaScript call,
instead of one Selenium round-trip per candidate element. On heavy pages
(enterprise CRMs, SPAs) with hundreds of hidden interactive elements, the
old per-element is_displayed()/get_attribute() approach could take
minutes just to build the list - before the LLM was ever called.
"""

from config import MAX_ELEMENTS_SENT_TO_LLM

INTERACTIVE_SELECTOR = (
    "a, button, input, textarea, select, "
    "[role='button'], [role='link'], [onclick]"
)

# Runs entirely inside the browser: finds candidates, filters to visible
# ones, and stops as soon as it has enough - all in a single round-trip.
_VISIBLE_FILTER_JS = """
const selector = arguments[0];
const maxCount = arguments[1];
const candidates = document.querySelectorAll(selector);
const visible = [];
for (const el of candidates) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width > 0 && rect.height > 0 &&
        style.visibility !== 'hidden' && style.display !== 'none') {
        visible.push(el);
        if (visible.length >= maxCount) break;
    }
}
return visible;
"""


def extract_elements(driver):
    try:
        # Selenium automatically converts the returned DOM nodes into
        # real WebElement objects - this is the ONE round-trip.
        visible_elements = driver.execute_script(
            _VISIBLE_FILTER_JS, INTERACTIVE_SELECTOR, MAX_ELEMENTS_SENT_TO_LLM
        )
    except Exception:
        visible_elements = []

    elements = []
    for index, el in enumerate(visible_elements):
        try:
            text = (el.get_attribute("innerText") or el.get_attribute("value") or "").strip()
            elements.append({
                "index": index,
                "tag": el.tag_name,
                "id": el.get_attribute("id") or "",
                "name": el.get_attribute("name") or "",
                "type": el.get_attribute("type") or "",
                "placeholder": el.get_attribute("placeholder") or "",
                "aria_label": el.get_attribute("aria-label") or "",
                "text": text[:80],
                "class": el.get_attribute("class") or "",
                "_element": el,
            })
        except Exception:
            continue

    return elements


def to_llm_payload(elements):
    """Strips the live WebElement reference before sending to the LLM
    (which only needs plain JSON-serialisable data)."""
    return [
        {k: v for k, v in el.items() if k != "_element"}
        for el in elements
    ]