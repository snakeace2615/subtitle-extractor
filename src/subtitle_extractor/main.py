from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence

from subtitle_extractor.batch import BatchExtractor
from subtitle_extractor.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-extractor",
        description="Scan the configured media directory once and extract source subtitles.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("scan", help="Scan once, process pending media, then exit")
    subparsers.add_parser("api", help="Start the optional FastAPI service")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    if args.command == "api":
        import uvicorn

        uvicorn.run(
            "subtitle_extractor.api:app",
            host=settings.host,
            port=settings.port,
            reload=False,
        )
        return 0

    try:
        summary = BatchExtractor(settings).run()
    except Exception as exc:
        logging.getLogger(__name__).exception("Batch scan failed")
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({"status": "complete", **summary.as_dict()}, ensure_ascii=False))
    return 1 if summary.failed else 0


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
