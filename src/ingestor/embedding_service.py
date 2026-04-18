"""
Service d'embeddings avec cache Redis.
Évite de ré-embedder des textes déjà vus (économise ~70% des appels Ollama).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Client Ollama avec cache Redis pour les embeddings."""

    def __init__(
        self,
        ollama_url: str,
        model: str,
        redis_url: str | None = None,
        cache_ttl: int = 86400,
    ) -> None:
        """Initialise le service d'embeddings.

        Args:
            ollama_url: URL de base Ollama (ex: http://ollama:11434).
            model: Nom du modèle d'embedding (ex: nomic-embed-text:v1.5).
            redis_url: URL Redis pour le cache (optionnel).
            cache_ttl: Durée de vie du cache en secondes (défaut: 24h).
        """
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._redis_url = redis_url
        self.cache_ttl = cache_ttl
        self._redis: aioredis.Redis | None = None
        self._http: httpx.AsyncClient | None = None
        self._cache_hits = 0
        self._cache_misses = 0

    async def connect(self) -> None:
        """Initialise les connexions Redis et HTTP."""
        redis_url = self._redis_url or os.getenv(
            "REDIS_CACHE_URL", "redis://redis:6379/1"
        )
        try:
            self._redis = aioredis.from_url(redis_url, decode_responses=False)
            await self._redis.ping()
            logger.info("Redis cache connected: %s", redis_url)
        except Exception as exc:
            logger.warning("Redis cache unavailable (%s), running without cache", exc)
            self._redis = None

        self._http = httpx.AsyncClient(timeout=60.0)

        # Télécharger le modèle si absent
        await self._pull_model()

    async def disconnect(self) -> None:
        """Ferme les connexions."""
        if self._redis:
            await self._redis.aclose()
        if self._http:
            await self._http.aclose()
        logger.info(
            "EmbeddingService disconnected (cache hits=%d, misses=%d)",
            self._cache_hits,
            self._cache_misses,
        )

    async def _pull_model(self) -> None:
        """S'assure que le modèle est disponible dans Ollama."""
        if not self._http:
            return
        try:
            resp = await self._http.post(
                f"{self.ollama_url}/api/pull",
                json={"name": self.model, "stream": False},
                timeout=300.0,
            )
            resp.raise_for_status()
            logger.info("Ollama model '%s' ready", self.model)
        except Exception as exc:
            logger.warning("Unable to pull model '%s': %s", self.model, exc)

    def _cache_key(self, text: str) -> str:
        """Génère une clé de cache déterministe pour un texte."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"embed:{self.model}:{text_hash}"

    async def embed_one(self, text: str) -> list[float]:
        """Embed un seul texte avec cache Redis.

        Args:
            text: Texte à embedder.

        Returns:
            Vecteur d'embedding (list[float]).

        Raises:
            RuntimeError: Si l'appel Ollama échoue.
        """
        cache_key = self._cache_key(text)

        # Vérifier le cache
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    self._cache_hits += 1
                    parsed = json.loads(cached)
                    if isinstance(parsed, list) and all(isinstance(x, int | float) for x in parsed):
                        return [float(x) for x in parsed]
            except Exception:
                pass

        self._cache_misses += 1

        # Appel Ollama
        if not self._http:
            raise RuntimeError("EmbeddingService not connected. Call connect() first.")

        resp = await self._http.post(
            f"{self.ollama_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Embedding model '{self.model}' not found on Ollama. "
                f"Pull it with: ollama pull {self.model}"
            )
        resp.raise_for_status()
        data = resp.json()
        embedding_any = data.get("embedding") if isinstance(data, dict) else None
        if not (isinstance(embedding_any, list) and all(isinstance(x, int | float) for x in embedding_any)):
            raise RuntimeError("Ollama returned an invalid embedding payload")
        embedding = [float(x) for x in embedding_any]

        # Mettre en cache
        if self._redis:
            try:
                await self._redis.setex(
                    cache_key,
                    self.cache_ttl,
                    json.dumps(embedding),
                )
            except Exception:
                pass

        return embedding

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed une liste de textes par batchs avec cache.

        Args:
            texts: Liste de textes à embedder.
            batch_size: Taille des batchs (défaut: 32).

        Returns:
            Liste de vecteurs d'embedding.
        """
        results: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            cache_hits: dict[int, list[float]] = {}
            to_compute: list[tuple[int, str]] = []

            # Vérifier cache pour chaque item
            for j, text in enumerate(batch):
                if self._redis:
                    try:
                        cached = await self._redis.get(self._cache_key(text))
                        if cached:
                            cache_hits[j] = json.loads(cached)
                            self._cache_hits += 1
                            continue
                    except Exception:
                        pass
                to_compute.append((j, text))

            # Calculer ceux non en cache
            for j, text in to_compute:
                emb = await self.embed_one(text)
                cache_hits[j] = emb

            # Recombiner dans l'ordre
            embeddings = [cache_hits[j] for j in range(len(batch))]
            results.extend(embeddings)

        return results

    @property
    def cache_stats(self) -> dict[str, float]:
        """Retourne les statistiques de cache."""
        total = self._cache_hits + self._cache_misses
        return {
            "hits": float(self._cache_hits),
            "misses": float(self._cache_misses),
            "total": float(total),
            "hit_rate_pct": round(self._cache_hits / total * 100, 1) if total else 0.0,
        }
