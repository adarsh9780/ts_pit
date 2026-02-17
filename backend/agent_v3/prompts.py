from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import yaml
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


@lru_cache(maxsize=32)
def load_chat_prompt(filename: str) -> ChatPromptTemplate:
    """Load prompt from prompts/{filename}.yaml"""
    path = Path(__file__).parent / "prompts" / f"{filename}.yaml"

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return ChatPromptTemplate.from_messages(
        [("system", config["system"]), MessagesPlaceholder("messages")]
    )
