"""Captures a value out of a live network API response using Chrome
DevTools Protocol (CDP) - no proxy, no paid tool, works with plain
Selenium + Chrome.

Typical use case: after clicking "Send OTP", the page fires an XHR/fetch
whose JSON body contains something like {"otp": "1234"}. This module
watches Chrome's network events for a response whose URL matches a
substring, pulls its JSON body, and extracts a field by dot-path.
"""

import base64
import json
import re
import time

_PATH_TOKEN = re.compile(r'([^.\[\]]+)|\[(\d+)\]')


def enable_network_capture(driver):
    """Turns on the CDP Network domain so response events start flowing
    into the Chrome performance log. Call this once, right after the
    driver is created."""
    driver.execute_cdp_cmd("Network.enable", {})


def _traverse(data, path: str):
    """Walks a dot/bracket path like 'data.otp' or 'result[0].otp'."""
    current = data
    for name, idx in _PATH_TOKEN.findall(path):
        if name:
            current = current[name]
        elif idx != "":
            current = current[int(idx)]
    return current


def capture_json_field(driver, url_contains: str, json_path: str,
                        timeout: float = 15, poll_interval: float = 0.5):
    """Polls Chrome's performance log for a network response whose URL
    contains `url_contains`, then extracts `json_path` from its JSON
    body. Returns the value as a string, or None if not found in time.
    """
    deadline = time.time() + timeout
    seen_request_ids = set()
    total_responses_seen = 0
    urls_seen = []

    while time.time() < deadline:
        try:
            logs = driver.get_log("performance")
        except Exception as e:
            print(f"   [debug] get_log failed: {e}")
            logs = []

        for entry in logs:
            try:
                message = json.loads(entry["message"])["message"]
            except Exception:
                continue

            if message.get("method") != "Network.responseReceived":
                continue

            params = message.get("params", {})
            response = params.get("response", {})
            url = response.get("url", "")
            request_id = params.get("requestId")

            total_responses_seen += 1
            if url and url not in urls_seen:
                urls_seen.append(url)

            if url_contains not in url or request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)

            try:
                body_result = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": request_id}
                )
            except Exception as e:
                print(f"   [debug] getResponseBody failed for {url}: {e}")
                continue

            body_text = body_result.get("body", "")
            if body_result.get("base64Encoded"):
                try:
                    body_text = base64.b64decode(body_text).decode("utf-8", errors="ignore")
                except Exception:
                    continue

            try:
                data = json.loads(body_text)
            except Exception:
                print(f"   [debug] response from {url} wasn't JSON: {body_text[:100]!r}")
                continue

            try:
                value = _traverse(data, json_path)
            except Exception as e:
                print(f"   [debug] json_path '{json_path}' not found in {url}: {e}")
                continue

            if value is not None:
                return str(value)

        time.sleep(poll_interval)

    print(f"   [debug] saw {total_responses_seen} network responses total in {timeout}s")
    api_urls = [u for u in urls_seen if "api" in u.lower()]
    print(f"   [debug] URLs containing 'api' ({len(api_urls)}): {api_urls}")
    return None