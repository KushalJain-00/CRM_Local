# services/prompts/__init__.py
"""Extraction prompt assembly: one master prompt, one contract, five source extensions."""
from .contact_extraction import (
    EXTRACTION_CONTRACT,
    MASTER_SYSTEM_PROMPT,
    SOURCE_EXTENSIONS,
    build_prompt,
)

__all__ = [
    "MASTER_SYSTEM_PROMPT",
    "EXTRACTION_CONTRACT",
    "SOURCE_EXTENSIONS",
    "build_prompt",
]
