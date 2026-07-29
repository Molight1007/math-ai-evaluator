from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from math_agent.entrypoint import (  # noqa: E402
    ReasoningAgent as _ReasoningAgent,
    _extract_chat_content,
)


class ReasoningAgent(_ReasoningAgent):
    """Official root-level entry point."""


__all__ = ["ReasoningAgent", "_extract_chat_content"]
