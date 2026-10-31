"""Executes a structured action (produced by the LLM) against a real
WebElement using Selenium, and works out the best available locator for
that element so it can be replayed later without an LLM."""

import time

from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, ElementNotInteractableException, NoSuchElementException,
    InvalidElementStateException, StaleElementReferenceException,
)

from config import DEFAULT_WAIT_SECONDS


class StepResult:
    def __init__(self, instruction, action, status, detail="", locator=None):
        self.instruction = instruction
        self.action = action
        self.status = status
        self.detail = detail
        self.locator = locator

    def to_dict(self):
        return {
            "instruction": self.instruction,
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
            "locator": self.locator,
        }


def best_locator_for(el_info: dict):
    if el_info.get("id"):
        return {"by": "ID", "value": el_info["id"]}
    if el_info.get("name"):
        return {"by": "NAME", "value": el_info["name"]}
    if el_info.get("placeholder"):
        return {"by": "CSS_SELECTOR", "value": f"[placeholder='{el_info['placeholder']}']"}
    if el_info.get("text"):
        tag = el_info.get("tag", "*")
        text = el_info["text"].replace("'", "\\'")
        return {"by": "XPATH", "value": f"//{tag}[normalize-space()='{text}']"}
    return None


def execute_action(driver, action: dict, element_info: dict = None):
    act = action.get("action")
    value = action.get("value")

    try:
        if act == "wait":
            seconds = float(value) if value else 2
            time.sleep(seconds)
            return True, f"waited {seconds}s"

        if act == "navigate":
            driver.get(value)
            return True, f"navigated to {value}"

        if act == "assert_text":
            WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(
                lambda d: value in d.page_source
            )
            return True, f"found text '{value}' on page"

        if element_info is None or "_element" not in element_info:
            return False, "no matching element resolved"

        el = element_info["_element"]
        WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(
            EC.element_to_be_clickable(el) if act in ("click", "submit", "hover")
            else EC.visibility_of(el)
        )

        if act in ("click", "submit"):
            el.click()
            return True, "clicked"

        if act == "type":
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.3)

            # Try 1: normal click + clear + send_keys
            try:
                WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.element_to_be_clickable(el))
                el.click()
                el.clear()
                el.send_keys(value)
            except (InvalidElementStateException, ElementNotInteractableException,
                    StaleElementReferenceException):
                pass  # fall through to JS fallback below

            actual = (el.get_attribute("value") or "").strip()
            if actual == str(value).strip():
                return True, f"typed '{value}' (verified)"

            # Try 2: JS fallback using the element's own prototype chain
            # (avoids "Illegal invocation" on iframe/custom-component fields).
            try:
                driver.execute_script(
                    """
                    const el = arguments[0];
                    const newValue = arguments[1];
                    let proto = Object.getPrototypeOf(el);
                    let descriptor;
                    while (proto && !descriptor) {
                        descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                        proto = Object.getPrototypeOf(proto);
                    }
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(el, newValue);
                    } else {
                        el.value = newValue;
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                    """,
                    el, value,
                )
            except Exception as e2:
                return False, f"type failed, JS fallback errored: {e2}"

            actual = (el.get_attribute("value") or "").strip()
            if actual == str(value).strip():
                return True, f"typed '{value}' (verified via JS fallback)"

            return False, (
                f"type FAILED verification: field shows '{actual}' "
                f"instead of '{value}' after both attempts"
            )

        if act == "select":
            Select(el).select_by_visible_text(value)
            return True, f"selected '{value}'"

        if act == "hover":
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).move_to_element(el).perform()
            return True, "hovered"

        if act == "assert_visible":
            visible = el.is_displayed()
            return visible, "element visible" if visible else "element not visible"

        return False, f"unknown action '{act}'"

    except (TimeoutException, ElementNotInteractableException, NoSuchElementException) as e:
        return False, f"selenium error: {e.__class__.__name__}"
    except Exception as e:
        return False, f"error: {e}"
