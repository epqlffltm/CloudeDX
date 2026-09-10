# app/tests/test_repair_unowned_uploads.py
"""seller_id=NULL 직접등록 복구 스크립트의 범위·dry-run·멱등성 테스트."""

import argparse

from sqlalchemy import select

from app.db import repository
from app.db.models import ItemRecord
from app.domain.models import CrawledItem
from app.domain.sources import UPLOAD
from app.tests.sellers import make_seller
from scripts import repair_unowned_uploads as repair


class _UseExistingSession:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _args(seller_id: int, *, prefix: str = "", apply: bool = False):
    return argparse.Namespace(seller_id=seller_id, url_prefix=prefix, apply=apply)


def _item(url: str, *, source: str = UPLOAD):
    return CrawledItem(
        source=source,
        brand="샤넬",
        title="샤넬 클래식 플랩백 미디움",
        price="1,000,000원",
        price_value=1_000_000,
        region=None,
        time_text=None,
        image_url=None,
        url=url,
        is_sold=False,
    )


async def _seller_id_for(session, url: str):
    return (
        await session.execute(select(ItemRecord.seller_id).where(ItemRecord.url == url))
    ).scalar_one()


async def test_dry_run_does_not_modify_rows(session, monkeypatch):
    seller_id = await make_seller(session, "복구 대상 상사")
    url = "https://repair.example/dry"
    await repository.upsert_items([_item(url)], session=session)

    monkeypatch.setattr(repair, "async_session", lambda: _UseExistingSession(session))

    result = await repair.run(_args(seller_id))

    assert result == 0
    assert await _seller_id_for(session, url) is None


async def test_apply_only_changes_unowned_uploads_matching_prefix(session, monkeypatch):
    seller_id = await make_seller(session, "복구 대상 상사")
    other_seller = await make_seller(session, "기존 소유 상사")

    target = "https://repair.example/mine/1"
    other_prefix = "https://repair.example/other/2"
    crawled = "https://repair.example/mine/crawled"
    already_owned = "https://repair.example/mine/already"

    await repository.upsert_items(
        [
            _item(target),
            _item(other_prefix),
            _item(crawled, source="중고나라"),
            _item(already_owned),
        ],
        session=session,
    )
    owned_row = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == already_owned))
    ).scalar_one()
    owned_row.seller_id = other_seller
    await session.commit()

    monkeypatch.setattr(repair, "async_session", lambda: _UseExistingSession(session))

    result = await repair.run(
        _args(seller_id, prefix="https://repair.example/mine/", apply=True)
    )

    assert result == 0
    assert await _seller_id_for(session, target) == seller_id
    assert await _seller_id_for(session, other_prefix) is None
    assert await _seller_id_for(session, crawled) is None
    assert await _seller_id_for(session, already_owned) == other_seller

    # 같은 명령을 다시 실행해도 더 바뀔 행이 없다.
    assert (
        await repair.run(
            _args(seller_id, prefix="https://repair.example/mine/", apply=True)
        )
        == 0
    )
    assert await _seller_id_for(session, target) == seller_id


async def test_missing_seller_returns_2_without_changes(session, monkeypatch):
    url = "https://repair.example/no-seller"
    await repository.upsert_items([_item(url)], session=session)

    monkeypatch.setattr(repair, "async_session", lambda: _UseExistingSession(session))

    result = await repair.run(_args(2_147_483_647, apply=True))

    assert result == 2
    assert await _seller_id_for(session, url) is None
