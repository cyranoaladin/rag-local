from __future__ import annotations


def generate_fake_embedding(text: str, dimension: int = 8) -> list[float]:
    """Return a deterministic pseudo-embedding for the given text."""
    if not text:
        return [0.0] * dimension
    seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
    factors = [7, 11, 13, 17, 19, 23, 29, 31]
    vector: list[float] = []
    for i in range(dimension):
        base = seed + factors[i % len(factors)] * (i + 1)
        # Keep the numbers small and deterministic for stable tests.
        vector.append(round((base % 997) / 997.0, 6))
    return vector
