"""
LangGraph Agent State
=====================
Defines the state schema for the trade surveillance AI agent.

Design decisions:
- Session-level memory (thread_id = session UUID, not alert ID)
- current_alert_id passed with each request for context
- Auto-context loading when alert is selected
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
        current_alert_id: The alert currently being viewed by the user.
                          Used for auto-context loading. Can be None if
                          user is on the alerts list page.
        summary: Running summary of older conversation for memory management.
                 Populated when conversation exceeds threshold length.
    """

    # Conversation messages with proper reducer
    messages: Annotated[list, add_messages]

    # Currently selected alert (optional - can query any alert)
    current_alert_id: Optional[str]

    # Running summary for long conversations
    summary: str
