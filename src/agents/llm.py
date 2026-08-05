"""Groq model configuration loaded from the local environment only."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_groq_model(*, temperature: float = 0.0) -> ChatGroq:
    """Create the shared Groq chat model without exposing its API key.

    ``GROQ_MODEL`` and ``GROQ_API_KEY`` must be defined in ``.env`` (or in the
    environment).  The model name remains configuration, not a secret.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    model_name = os.getenv("GROQ_MODEL")
    api_key = os.getenv("GROQ_API_KEY")
    if not model_name:
        raise RuntimeError("GROQ_MODEL is required in .env")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required in .env")
    return ChatGroq(model=model_name, api_key=api_key, temperature=temperature)
