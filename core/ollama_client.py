"""Talks to a locally running Ollama server to turn a plain-language
instruction + a snapshot of the page's interactive elements into a
structured automation action.
"""

import json
import requests

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS

SYSTEM_PROMPT = """You are a browser automation planner.
You are given:
1. A natural language instruction describing one browser step.
2. A numbered list of interactive elements currently visible on the page.

Respond with ONLY a single JSON object, no markdown, no code fences, no
explanation. The JSON must match this schema exactly:

{
  "action": "click" | "type" | "select" | "hover" | "submit" | "assert_text" | "assert_visible" | "wait" | "navigate",
  "element_index": <integer or null>,
  "value": <string or null>
}

Rules:
- "element_index" must be the index of the best-matching element from the
  provided list, or null if the action does not target a listed element
  (e.g. "wait", "navigate", or a page-level "assert_text").
- If the action clearly needs an element from the list but NONE of the
  listed elements is a good match, set "element_index" to -1.
- "value" holds text to type, the option to select, seconds to wait,
  text to assert, or the URL to navigate to. Use null if not applicable.
- Never invent an element that is not in the list.
"""


def build_prompt(instruction: str, elements: list) -> str:
    element_lines = []
    for el in elements:
        element_lines.append(
            f"{el['index']}: <{el['tag']}> "
            f"text='{el.get('text', '')}' id='{el.get('id', '')}' "
            f"name='{el.get('name', '')}' type='{el.get('type', '')}' "
            f"placeholder='{el.get('placeholder', '')}' "
            f"aria_label='{el.get('aria_label', '')}'"
        )
    elements_block = "\n".join(element_lines) if element_lines else "(no interactive elements found)"

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Instruction: {instruction}\n\n"
        f"Visible interactive elements:\n{elements_block}\n\n"
        f"JSON:"
    )


def ask_llm(instruction: str, elements: list, model: str = OLLAMA_MODEL) -> dict:
    """Sends the instruction + element list to the local Ollama model and
    returns a parsed action dict. Raises on unrecoverable errors."""

    prompt = build_prompt(instruction, elements)

    response = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 150,
                "num_ctx": 2048,
            },
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw_text = response.json().get("response", "").strip()

    try:
        action = json.loads(raw_text)
    except json.JSONDecodeError:
        # Some models wrap JSON in extra text even with format=json; try to
        # salvage the first {...} block.
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"Model did not return valid JSON: {raw_text}")
        action = json.loads(raw_text[start:end + 1])

    action.setdefault("element_index", None)
    action.setdefault("value", None)
    return action
