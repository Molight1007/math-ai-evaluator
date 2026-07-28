from math_agent.entrypoint import (
    ReasoningAgent as _ReasoningAgent,
    _extract_chat_content,
)


class ReasoningAgent(_ReasoningAgent):
    """Installed wheel entry point."""

__all__ = ["ReasoningAgent", "_extract_chat_content"]
