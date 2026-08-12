# app/crawler/daangn/run.py

"""
당근마켓 크롤러 터미널 진입점.
사용: uv run python -m app.crawler.daangn.run --brand "샤넬"
     uv run python -m app.crawler.daangn.run --all-brands
"""

import argparse
import asyncio
from pathlib import Path

from app.crawler.base import save_json
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.domain.brands import LUXURY_BRANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="당근 중고거래 명품 가방 검색 결과 크롤러"
    )

    parser.add_argument(
        "--brand",
        default="샤넬",
        help='브랜드명. 예: --brand "샤넬" (검색어는 "샤넬 가방"으로 자동 생성됨)',
    )
    parser.add_argument(
        "--all-brands",
        action="store_true",
        help=f"--brand 대신 기본 브랜드 목록({', '.join(LUXURY_BRANDS)})을 전부 순회한다.",
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


async def _crawl_brand(args: argparse.Namespace, brand: str) -> list:
    config = DaangnCrawlerConfig(
        brand=brand,
        region_code=args.region_code,
        headless=not args.show_browser,
        scroll_count=max(0, args.scrolls),
    )
    crawler = DaangnCrawler(config)

    print(f"[daangn] 검색 시작: {config.query}")
    items = await crawler.crawl()
    print(f"[daangn] '{brand}' {len(items)}건")
    return items


async def _run(args: argparse.Namespace) -> None:
    brands = list(LUXURY_BRANDS) if args.all_brands else [args.brand]

    all_items = []
    for brand in brands:
        all_items.extend(await _crawl_brand(args, brand))

    output_path = Path(args.output)
    save_json(all_items, output_path)

    print(f"[daangn] 전체 수집 완료: {len(all_items)}건")
    print(f"[daangn] 임시 저장: {output_path.resolve()}")

    for item in all_items[:5]:
        print(
            f"- [{item.brand}] {item.title} | "
            f"{item.price or '가격정보없음'} | "
            f"{item.region or '지역정보없음'}"
        )


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

