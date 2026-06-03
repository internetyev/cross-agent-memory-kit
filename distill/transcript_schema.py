from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class TranscriptMessage:
    role: MessageRole
    text: str
    timestamp: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedTranscript:
    agent: str
    session_id: str
    source_path: Optional[Path]
    messages: list[TranscriptMessage]
    cwd: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def user_assistant_text(self) -> str:
        chunks = []
        for message in self.messages:
            text = message.text.strip()
            if text:
                chunks.append(f"[{message.role.upper()}]\n{text}")
        return "\n\n".join(chunks)
