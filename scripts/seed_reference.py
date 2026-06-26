#!/usr/bin/env python3
"""CLI: seed reference data.

Usage::

    python -m scripts.seed_reference
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make app importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_session_factory
from app.services.seed import seed_all


async def main() -> int:
    factory = get_session_factory()
    async with factory() as session:
        counts = await seed_all(session)
    print("Seed complete:")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))