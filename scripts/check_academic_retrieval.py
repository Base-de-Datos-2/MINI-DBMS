"""Verify academic retrieval against the running unified server."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx2

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.academic_retrieval import InvalidQuestion, RetrievalError, retrieve_academic


async def _retrieve(base_url: str, question: str):
    async with httpx2.AsyncClient(trust_env=False) as client:
        return await retrieve_academic(question, base_url=base_url, client=client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/parte5")
    parser.add_argument("--question", required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_retrieve(args.base_url, args.question))
    except (InvalidQuestion, RetrievalError, httpx2.InvalidURL) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
