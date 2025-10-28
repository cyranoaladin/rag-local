from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from mm_adapter import Modalite


class ChunkModel(BaseModel):
    text: str = Field(max_length=8000)
    modality: Modalite
    meta: Dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    status: str
    added: int = 0
    skipped: int = 0
    modalities: Dict[str, int] = Field(default_factory=dict)
