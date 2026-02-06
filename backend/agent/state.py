"""
LangGraph Agent State
=====================
Defines the state schema for the trade surveillance AI agent.

Design decisions:
- Session-level memory (thread_id = session UUID per ticker)
- Alert context is now passed in user messages (not state)
- Summary field for managing long conversations
"""

from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    State for the trade surveillance agent.

    Attributes:
        messages: Conversation history with add_messages reducer for proper
                  message handling (deduplication, appending, removal).
        summary: Running summary of older conversation for memory management.
                 Populated when conversation exceeds threshold length.
    """

    # Conversation messages with proper reducer
    messages: Annotated[list, add_messages]

    # Running summary for long conversations
    summary: str
