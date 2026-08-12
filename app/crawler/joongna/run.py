# app/crawler/joongna/run.py

"""
중고나라 크롤러 터미널 진입점.
사용: uv run python -m app.crawler.joongna.run --brand "구찌" --pages 5
     uv run python -m app.crawler.joongna.run --all-brands
"""

import argparse
import asyncio
from pathlib import Path

from app.crawler.base import save_json
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.domain.brands import LUXURY_BRANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="중고나라 명품 가방 검색 결과 크롤러")

    parser.add_argument(
        "--brand",
        default="구찌",
        help='브랜드명. 예: --brand "구찌" (검색어는 "구찌 가방"으로 자동 생성됨)',
    )
    parser.add_argument(
        "--all-brands",
        action="store_true",
        help=f"--brand 대신 기본 브랜드 목록({', '.join(LUXURY_BRANDS)})을 전부 순회한다.",
    )
    parser.add_argument(
        "--category",
        default="103",
        help="카테고리 코드 (기본값은 여성 가방 카테고리로 추정)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="브랜드당 최대 페이지 수",
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


async def _crawl_brand(args: argparse.Namespace, brand: str) -> list:
    config = JoongnaCrawlerConfig(
        brand=brand,
        category=args.category,
        max_pages=args.pages,
        headless=not args.show_browser,
    )
    crawler = JoongnaCrawler(config)

    print(f"[joongna] 검색 시작: {config.keyword}")
    items = await crawler.crawl()
    print(f"[joongna] '{brand}' {len(items)}건")
    return items


async def _run(args: argparse.Namespace) -> None:
    brands = list(LUXURY_BRANDS) if args.all_brands else [args.brand]

    all_items = []
    for brand in brands:
        all_items.extend(await _crawl_brand(args, brand))

    output_path = Path(args.output)
    save_json(all_items, output_path)

    print(f"[joongna] 전체 수집 완료: {len(all_items)}건")
    print(f"[joongna] 임시 저장: {output_path.resolve()}")

    for item in all_items[:5]:
        print(f"- [{item.brand}] {item.title} | {item.price or '가격정보없음'}")


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

