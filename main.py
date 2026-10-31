"""
AI-assisted Selenium automation runner.

Usage:
    python main.py --url "https://example.com" --steps steps.txt
    python main.py --url "https://example.com" --steps steps.txt --headless --model llama3.1

You provide:
  - a starting URL
  - a plain-language steps file (one instruction per line)

The tool uses a local Ollama LLM to work out what each instruction means
in terms of real page elements, executes it with Selenium, and at the
end produces:
  - automation_output/run_log.json      (pass/fail detail per step)
  - automation_output/test_generated.py (reusable Selenium+pytest script,
    no LLM needed to run it again)
  - automation_output/report.html       (simple readable report)
"""

import argparse
import json
import os
import re
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import (
    OUTPUT_DIR, GENERATED_TEST_FILENAME, RUN_LOG_FILENAME,
    REPORT_FILENAME, OLLAMA_MODEL,
)
from core.dom_extractor import extract_elements, to_llm_payload
from core.ollama_client import ask_llm
from core.executor import execute_action, best_locator_for, StepResult
from core.test_generator import generate_pytest_file
from core.network_capture import enable_network_capture, capture_json_field

CAPTURE_PATTERN = re.compile(r"^capture_api_value\s+(.*)$", re.IGNORECASE)
NAVIGATE_PATTERN = re.compile(r"^navigate\s+to\s+(\S+)$", re.IGNORECASE)
KV_PATTERN = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
VAR_PATTERN = re.compile(r"\{(\w+)\}")


def read_steps(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def build_driver(headless: bool):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    # Needed so we can read network responses via CDP (used for
    # capture_api_value steps, e.g. pulling an OTP out of an API call).
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    enable_network_capture(driver)
    return driver


def parse_capture_line(line: str):
    """Parses a line like:
    capture_api_value url_contains="send-otp" json_path="otp" store_as="OTP"
    Returns a dict of the key="value" pairs, or None if the line isn't
    a capture command.
    """
    m = CAPTURE_PATTERN.match(line.strip())
    if not m:
        return None
    return dict(KV_PATTERN.findall(m.group(1)))


def substitute_vars(text: str, session_vars: dict):
    """Replaces {VAR} in text with a previously captured value. Returns
    (resolved_text, variable_name_used_or_None)."""
    used = {"name": None}

    def repl(match):
        name = match.group(1)
        if name in session_vars:
            used["name"] = name
            return session_vars[name]
        return match.group(0)

    resolved = VAR_PATTERN.sub(repl, text)
    return resolved, used["name"]


def resolve_element(elements: list, index: int):
    for el in elements:
        if el["index"] == index:
            return el
    return None


def ask_user_for_manual_locator(instruction: str):
    print("\n[MANUAL INPUT NEEDED] Could not confidently match an element for:")
    print(f"    \"{instruction}\"")
    print("Enter a CSS selector for this element (or press Enter to skip this step):")
    value = input("> ").strip()
    return value or None


def run(url: str, steps_path: str, model: str, headless: bool):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    steps = read_steps(steps_path)
    driver = build_driver(headless)
    results = []
    session_vars = {}

    try:
        driver.get(url)

        print("Warming up the AI model, please wait (one-time, 30-90s)...")
        try:
            ask_llm("warm up", [], model=model)
        except Exception:
            pass
        print("Model warmed up. Starting steps now.\n")

        for raw_instruction in steps:
            # --- Deterministic network-capture step (no LLM involved) ---
            capture_spec = parse_capture_line(raw_instruction)
            if capture_spec:
                print(f"\n>> [CAPTURE] {raw_instruction}")
                timeout = float(capture_spec.get("timeout", 15))
                store_as = capture_spec.get("store_as", "VALUE")
                value = capture_json_field(
                    driver,
                    capture_spec.get("url_contains", ""),
                    capture_spec.get("json_path", ""),
                    timeout=timeout,
                )
                if value is not None:
                    session_vars[store_as] = value
                    print(f"   [PASS] captured {store_as} = {value}")
                    status, detail = "pass", f"captured {store_as}={value}"
                else:
                    print(f"   [FAIL] could not capture {store_as} within {timeout}s")
                    status, detail = "fail", f"timed out waiting for {store_as}"

                results.append({
                    "instruction": raw_instruction,
                    "action": "capture_api_value",
                    "status": status,
                    "detail": detail,
                    "locator": None,
                    "value": value,
                    "store_as": store_as,
                    "url_contains": capture_spec.get("url_contains", ""),
                    "json_path": capture_spec.get("json_path", ""),
                })
                continue

            # --- Deterministic navigate step (no LLM involved either) ---
            nav_match = NAVIGATE_PATTERN.match(raw_instruction.strip())
            if nav_match:
                target_url = nav_match.group(1)
                print(f"\n>> [NAVIGATE] {raw_instruction}")
                try:
                    driver.get(target_url)
                    print(f"   [PASS] navigated to {target_url}")
                    results.append({
                        "instruction": raw_instruction, "action": "navigate",
                        "status": "pass", "detail": f"navigated to {target_url}",
                        "locator": None, "value": target_url, "value_var": None,
                    })
                except Exception as e:
                    print(f"   [FAIL] {e}")
                    results.append({
                        "instruction": raw_instruction, "action": "navigate",
                        "status": "fail", "detail": str(e),
                        "locator": None, "value": target_url, "value_var": None,
                    })
                continue

            # --- Normal instruction, resolve any {VAR} first, then ask the LLM ---
            instruction, value_var = substitute_vars(raw_instruction, session_vars)
            print(f"\n>> {instruction}")
            t0 = time.time()
            elements = extract_elements(driver)
            t1 = time.time()
            print(f"   [timing] element extraction took {t1 - t0:.1f}s, found {len(elements)} elements")
            payload = to_llm_payload(elements)

            try:
                action = ask_llm(instruction, payload, model=model)
                t2 = time.time()
                print(f"   [timing] LLM call took {t2 - t1:.1f}s")
            except Exception as e:
                print(f"   LLM error: {e}")
                results.append(StepResult(instruction, "unknown", "fail", str(e)).to_dict())
                continue

            element_info = None
            locator = None

            if action.get("element_index") is not None:
                idx = action["element_index"]
                if idx == -1:
                    manual_css = ask_user_for_manual_locator(instruction)
                    if manual_css:
                        try:
                            web_el = driver.find_element("css selector", manual_css)
                            element_info = {"_element": web_el}
                            locator = {"by": "CSS_SELECTOR", "value": manual_css}
                        except Exception as e:
                            print(f"   Manual selector failed: {e}")
                    if element_info is None:
                        results.append(StepResult(instruction, action.get("action", "unknown"),
                                                   "manual", "no element resolved").to_dict())
                        continue
                else:
                    element_info = resolve_element(elements, idx)
                    if element_info:
                        locator = best_locator_for(element_info)

            success, detail = execute_action(driver, action, element_info)
            status = "pass" if success else "fail"
            print(f"   [{status.upper()}] {detail}")

            step_dict = StepResult(
                instruction, action.get("action", "unknown"), status, detail, locator
            ).to_dict()
            step_dict["value"] = action.get("value")
            step_dict["value_var"] = value_var  # set if {VAR} was substituted in
            results.append(step_dict)

    finally:
        driver.quit()

    log_path = os.path.join(OUTPUT_DIR, RUN_LOG_FILENAME)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    test_path = os.path.join(OUTPUT_DIR, GENERATED_TEST_FILENAME)
    generate_pytest_file(url, results, test_path)

    write_html_report(url, results, os.path.join(OUTPUT_DIR, REPORT_FILENAME))

    passed = sum(1 for r in results if r["status"] == "pass")
    print(f"\n=== Done: {passed}/{len(results)} steps passed ===")
    print(f"Log:            {log_path}")
    print(f"Generated test: {test_path}")
    print(f"Report:         {os.path.join(OUTPUT_DIR, REPORT_FILENAME)}")


def write_html_report(url: str, results: list, path: str):
    rows = ""
    for r in results:
        color = {"pass": "#1a7f37", "fail": "#c0392b", "manual": "#b8860b"}.get(r["status"], "#333")
        rows += (
            "<tr>"
            f"<td>{r['instruction']}</td>"
            f"<td>{r['action']}</td>"
            f"<td style='color:{color};font-weight:bold'>{r['status'].upper()}</td>"
            f"<td>{r['detail']}</td>"
            "</tr>"
        )

    html = f"""<html><head><meta charset="utf-8">
<title>Automation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f4f4f4; }}
</style></head><body>
<h2>Automation Report</h2>
<p><b>URL:</b> {url}</p>
<table>
<tr><th>Instruction</th><th>Action</th><th>Status</th><th>Detail</th></tr>
{rows}
</table>
</body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="AI-assisted Selenium automation runner")
    parser.add_argument("--url", required=True, help="Starting URL to open")
    parser.add_argument("--steps", required=True, help="Path to a text file with one plain-language step per line")
    parser.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model name (default: llama3.1)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    args = parser.parse_args()

    if not os.path.exists(args.steps):
        print(f"Steps file not found: {args.steps}")
        sys.exit(1)

    run(args.url, args.steps, args.model, args.headless)


if __name__ == "__main__":
    main()