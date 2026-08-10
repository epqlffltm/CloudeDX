# app/crawler/daangn/run.py

"""
당근마켓 크롤러 터미널 진입점.
사용: uv run python -m app.crawler.daangn.run --query "아이폰"
"""

import argparse
import asyncio
from pathlib import Path

from app.crawler.base import save_json
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="당근 중고거래 검색 결과 크롤러"
    )

    parser.add_argument(
        "--query",
        required=True,
        help='검색어. 예: --query "아이폰"',
    )
    parser.add_argument(
        "--region-code",
        default=None,
        help=(
            "선택 사항. 당근 URL의 in 파라미터에 들어가는 지역 코드. "
            '예: "성수동2가-6141"'
        ),
    )
    parser.add_argument(
        "--output",
        default="data/crawled_items.json",
        help="임시 JSON 저장 경로. DB 연결 후 제거 가능.",
    )
    parser.add_argument(
        "--scrolls",
        type=int,
        default=6,
        help="최대 스크롤 횟수",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="브라우저 창을 실제로 표시한다.",
    )

    return parser


async def _run(args: argparse.Namespace) -> None:
    config = DaangnCrawlerConfig(
        query=args.query,
        region_code=args.region_code,
        headless=not args.show_browser,
        scroll_count=max(0, args.scrolls),
    )
    crawler = DaangnCrawler(config)

    print(f"[daangn] 검색 시작: {args.query}")
    items = await crawler.crawl()

    output_path = Path(args.output)
    save_json(items, output_path)

    print(f"[daangn] 수집 완료: {len(items)}건")
    print(f"[daangn] 임시 저장: {output_path.resolve()}")

    for item in items[:5]:
        print(
            f"- {item.title} | "
            f"{item.price or '가격정보없음'} | "
            f"{item.region or '지역정보없음'}"
        )


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
