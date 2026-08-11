# app/db/repository.py

"""
크롤링 결과(CrawledItem)를 DB에 저장하는 함수.
url을 유니크 키로 써서 이미 있는 매물이면 갱신(last_seen_at 포함), 새 매물이면 insert한다
(PostgreSQL의 INSERT ... ON CONFLICT DO UPDATE).
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.crawler.models import CrawledItem
from app.db.engine import async_session
from app.db.models import ItemRecord


async def upsert_items(items: list[CrawledItem]) -> None:
    """items를 한 트랜잭션으로 upsert. 빈 리스트면 아무것도 안 한다."""
    if not items:
        return

    async with async_session() as session:
        for item in items:
            stmt = pg_insert(ItemRecord).values(
                source=item.source,
                brand=item.brand,
                title=item.title,
                price=item.price,
                price_value=item.price_value,
                region=item.region,
                time_text=item.time_text,
                image_url=item.image_url,
                url=item.url,
                is_sold=item.is_sold,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ItemRecord.url],
                set_={
                    "source": stmt.excluded.source,
                    "brand": stmt.excluded.brand,
                    "title": stmt.excluded.title,
                    "price": stmt.excluded.price,
                    "price_value": stmt.excluded.price_value,
                    "region": stmt.excluded.region,
                    "time_text": stmt.excluded.time_text,
                    "image_url": stmt.excluded.image_url,
                    "is_sold": stmt.excluded.is_sold,
                    "last_seen_at": func.now(),
                    # first_seen_at은 의도적으로 안 건드린다 (최초 발견 시점 유지).
                },
            )
            await session.execute(stmt)

        await session.commit()
