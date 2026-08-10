#app/crawler/run.py

"""
터미널에서 실행하는 진입점
"""

import argparse
import json
from pathlib import Path

from app.crawler.config import CrawlerConfig
from app.crawler.crawler import DaangnCrawler


def save_json(items, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = [item.to_dict() for item in items]

    output_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


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
        help="Chrome 창을 실제로 표시한다.",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    config = CrawlerConfig(
        headless=not args.show_browser,
        scroll_count=max(0, args.scrolls),
    )

    crawler = DaangnCrawler(config)

    print(f"[crawler] 검색 시작: {args.query}")

    items = crawler.crawl(
        args.query,
        region_code=args.region_code,
    )

    output_path = Path(args.output)
    save_json(items, output_path)

    print(f"[crawler] 수집 완료: {len(items)}건")
    print(f"[crawler] 임시 저장: {output_path.resolve()}")

    for item in items[:5]:
        print(
            f"- {item.title} | "
            f"{item.price or '가격정보없음'} | "
            f"{item.region or '지역정보없음'}"
        )


if __name__ == "__main__":
    main()
