"""Groq model configuration loaded from the local environment only."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPECS = {
    # The declared model is within the assignment's <=10B parameter limit.
    "llama-3.1-8b-instant": {"parameter_size": "8B", "parameters": 8_000_000_000},
}


def get_groq_model_config() -> tuple[str, dict[str, int | str]]:
    """Load and validate the configured Groq model without returning secrets."""
    load_dotenv(PROJECT_ROOT / ".env")
    model_name = os.getenv("GROQ_MODEL")
    if not model_name:
        raise RuntimeError("GROQ_MODEL is required in .env")
    specification = MODEL_SPECS.get(model_name)
    if specification is None:
        raise RuntimeError(f"GROQ_MODEL {model_name!r} is not approved in MODEL_SPECS")
    if int(specification["parameters"]) > 10_000_000_000:
        raise RuntimeError("Configured model exceeds the 10B parameter assignment limit")
    return model_name, specification


def create_groq_model(*, temperature: float = 0.0) -> ChatGroq:
    """Create the shared Groq chat model without exposing its API key.

    ``GROQ_MODEL`` and ``GROQ_API_KEY`` must be defined in ``.env`` (or in the
    environment).  The model name remains configuration, not a secret.
    """
    model_name, _ = get_groq_model_config()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required in .env")
    return ChatGroq(model=model_name, api_key=api_key, temperature=temperature)
