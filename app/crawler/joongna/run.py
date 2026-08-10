# app/crawler/joongna/run.py

"""
중고나라 크롤러 터미널 진입점.
사용: uv run python -m app.crawler.joongna.run --keyword "구찌" --pages 5
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="중고나라 검색 결과 크롤러")

    parser.add_argument(
        "--keyword",
        default="구찌",
        help='검색어. 예: --keyword "구찌"',
    )
    parser.add_argument(
        "--category",
        default="103",
        help="카테고리 코드",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="최대 페이지 수",
    )
    parser.add_argument(
        "--output",
        default="data/joongna_crawled_items.json",
        help="임시 JSON 저장 경로. DB 연결 후 제거 가능.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="브라우저 창을 실제로 표시한다.",
    )

    return parser


async def _run(args: argparse.Namespace) -> None:
    config = JoongnaCrawlerConfig(
        keyword=args.keyword,
        category=args.category,
        max_pages=args.pages,
        headless=not args.show_browser,
    )
    crawler = JoongnaCrawler(config)

    print(f"[joongna] 검색 시작: {args.keyword}")
    items = await crawler.crawl()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [item.to_dict() for item in items],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[joongna] 수집 완료: {len(items)}건")
    print(f"[joongna] 임시 저장: {output_path.resolve()}")

    for item in items[:5]:
        print(f"- {item.title} | {item.price or '가격정보없음'}")


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
