from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .embedding_utils import generate_fake_embedding

app = FastAPI(title="Mock Ollama API")


class EmbeddingRequest(BaseModel):
    model: str
    prompt: str


class EmbeddingResponse(BaseModel):
    embedding: list[float]


@app.post("/api/embeddings", response_model=EmbeddingResponse)
def create_embedding(payload: EmbeddingRequest) -> EmbeddingResponse:
    """Return a deterministic embedding for integration tests."""
    vector = generate_fake_embedding(payload.prompt)
    return EmbeddingResponse(embedding=vector)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
