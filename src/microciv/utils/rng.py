"""Seeded random helpers."""

from __future__ import annotations

import random


def build_rng(seed: int) -> random.Random:
    """Create a deterministic RNG for the given seed."""
    return random.Random(seed)
