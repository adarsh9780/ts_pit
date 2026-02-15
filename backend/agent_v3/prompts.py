from __future__ import annotations

from pathlib import Path
import yaml
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


def load_chat_prompt(filename: str) -> ChatPromptTemplate:
    """Load prompt from prompts/{filename}.yaml"""
    path = Path(__file__).parent / "prompts" / f"{filename}.yaml"

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    return ChatPromptTemplate.from_messages(
        [("system", config["system"]), MessagesPlaceholder("messages")]
    )
