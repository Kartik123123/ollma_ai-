"""Central configuration for the AI-driven Selenium automation framework."""

import os

# Ollama local LLM server settings
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT_SECONDS = 120

# Selenium settings
DEFAULT_WAIT_SECONDS = 10
MAX_ELEMENTS_SENT_TO_LLM = 40

# Output paths
OUTPUT_DIR = os.environ.get("AUTOMATION_OUTPUT_DIR", "automation_output")
GENERATED_TEST_FILENAME = "test_generated.py"
RUN_LOG_FILENAME = "run_log.json"
REPORT_FILENAME = "report.html"
