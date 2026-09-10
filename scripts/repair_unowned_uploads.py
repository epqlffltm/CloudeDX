#!/usr/bin/env python3
"""
기존 seller_id=NULL 직접등록 매물을 특정 판매자에게 연결하는 복구 도구.

기본은 DRY RUN이다. 실제 수정은 --apply 를 명시해야 한다.
"""

import argparse
import asyncio

from sqlalchemy import func, select, update

from app.db.engine import async_session
from app.db.models import ItemRecord, Seller
from app.domain.sources import UPLOAD


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seller-id", type=int, required=True)
    parser.add_argument(
        "--url-prefix",
        default="",
        help="선택: 이 문자열로 시작하는 URL만 복구",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 UPDATE 실행. 생략하면 dry-run",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    async with async_session() as session:
        seller = await session.get(Seller, args.seller_id)
        if seller is None:
            print(f"ERROR: sellers.id={args.seller_id}가 없습니다.")
            return 2

        conditions = [
            ItemRecord.source == UPLOAD,
            ItemRecord.seller_id.is_(None),
        ]
        if args.url_prefix:
            conditions.append(ItemRecord.url.startswith(args.url_prefix))

        count = (
            await session.execute(
                select(func.count()).select_from(ItemRecord).where(*conditions)
            )
        ).scalar_one()

        print(f"대상 판매자: {seller.name} (id={seller.id})")
        print(f"seller_id=NULL 직접등록 매물: {count}건")

        if count == 0:
            return 0

        sample = (
            (
                await session.execute(
                    select(ItemRecord.id, ItemRecord.title, ItemRecord.url)
                    .where(*conditions)
                    .order_by(ItemRecord.id)
                    .limit(20)
                )
            )
            .all()
        )
        print("\n샘플:")
        for item_id, title, url in sample:
            print(f"  {item_id}: {title} | {url}")

        if not args.apply:
            print("\nDRY RUN입니다. 실제 반영하려면 --apply를 붙이세요.")
            return 0

        result = await session.execute(
            update(ItemRecord)
            .where(*conditions)
            .values(seller_id=args.seller_id)
            .returning(ItemRecord.id)
        )
        changed = len(result.scalars().all())
        await session.commit()

        print(f"\n완료: {changed}건을 seller_id={args.seller_id}로 연결했습니다.")
        return 0


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
