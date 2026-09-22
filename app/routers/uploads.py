# app/routers/uploads.py
"""
기업고객 전용 CSV/사진 업로드와 '내 매물' 조회.

핵심 원칙:
- 직접등록 매물은 반드시 로그인 계정의 seller_id와 연결한다.
- seller_id가 설정되지 않았거나 실제 sellers 행이 없으면 새 매물을 만들지 않는다.
- '내 매물'은 source=직접등록 전체가 아니라 현재 로그인 판매자의 매물만 반환한다.
- 사진 수정 권한은 기존 owns_item()의 엄격한 소유권 규칙을 그대로 유지한다.
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_role
from app.config import MAX_UPLOAD_BYTES, WRITE_TIMEOUT_SECONDS
from app.db import repository
from app.db.engine import get_session
from app.db.models import ItemRecord, Seller
from app.domain.csv_import import REQUIRED_COLUMNS, parse_csv
from app.domain.image_security import MAX_UPLOAD_BYTES as MAX_IMAGE_BYTES
from app.domain.image_security import ImageRejected, sanitize_image
from app.domain.ownership import owns_item
from app.domain.sources import UPLOAD
from app.domain.storage import (
    StorageUnavailable,
    delete_image,
    object_name_from_url,
    public_url,
    save_image,
)
from app.schemas.auth import UploadResponse
from app.schemas.products import ListingListResponse, ListingOut
from app.schemas.uploads import ImageUploadResponse, ItemDeleteResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])


async def _read_body_capped(request: Request, limit: int) -> bytes:
    """요청 본문을 읽되 limit 바이트를 넘으면 읽는 도중 413으로 중단한다."""
    declared = request.headers.get("content-length")

    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"파일이 너무 큽니다. 최대 {limit // (1024 * 1024)}MB까지 가능합니다.",
        )

    chunks: list[bytes] = []
    size = 0

    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"파일이 너무 큽니다. 최대 {limit // (1024 * 1024)}MB까지 가능합니다.",
            )
        chunks.append(chunk)

    return b"".join(chunks)


async def _require_client_seller(session: AsyncSession, user: User) -> Seller:
    """
    사진/직접등록 기능을 쓰는 client 계정은 반드시 실제 Seller와 연결되어야 한다.

    예전 동작은 CLIENT_SELLER_ID=0 또는 존재하지 않는 id여도 CSV 업로드를 200으로
    성공시켰다. 그 결과 seller_id=NULL 매물이 생기고, 이후 사진 업로드는 owns_item()
    검사에서 영구히 403이 됐다. 이제는 잘못된 상태의 데이터를 만들기 전에 거절한다.
    """
    if user.seller_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "기업고객 계정에 판매자가 연결되어 있지 않습니다. "
                "CLIENT_SELLER_ID를 실제 sellers.id로 설정해 주세요."
            ),
        )

    seller = await session.get(Seller, user.seller_id)
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CLIENT_SELLER_ID={user.seller_id}에 해당하는 판매자가 없습니다. "
                "판매자 데이터를 먼저 등록한 뒤 다시 시도해 주세요."
            ),
        )

    return seller


async def _load_my_item(
    session: AsyncSession, user: User, item_id: int
) -> ItemRecord:
    """
    수정·삭제 대상 매물을 꺼내면서 소유권까지 확인한다.

    사진 등록과 매물 내리기가 같은 판단을 해야 하므로 한 함수로 모았다. 없으면
    404, 남의 것이면 403이다. 소유 판단은 owns_item() 하나만 쓴다 — 직접등록이
    아니거나 판매자가 다르면 거절이다(app/domain/ownership.py).
    """
    item = await session.get(ItemRecord, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 매물을 찾을 수 없습니다.",
        )

    if not owns_item(
        account_seller_id=user.seller_id,
        item_source=item.source,
        item_seller_id=item.seller_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 계정이 등록한 매물만 수정할 수 있습니다.",
        )

    return item


async def _commit_guarded(session: AsyncSession, what: str) -> None:
    """
    쓰기 제한시간을 걸고 커밋한다. 실패하면 롤백하고 503으로 돌린다.

    제한시간을 두는 이유: DB 가 느려질 때 요청이 무한정 붙잡혀 있으면 파드의
    커넥션이 모두 소진되어 읽기까지 멈춘다. 빨리 포기하고 재시도를 유도한다.
    """
    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            await session.commit()
    except (TimeoutError, SQLAlchemyError) as exc:
        await session.rollback()
        logger.warning("%s 실패: %s: %s", what, type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc


def _to_listing(item: ItemRecord) -> ListingOut:
    """직접등록 매물을 프론트엔드 ListingOut 계약으로 변환한다."""
    return ListingOut(
        id=item.id,
        source=item.source,
        title=item.clean_title or item.title,
        brand=item.brand,
        category=item.category,
        price=item.price_value,
        image_url=item.image_url,
        item_url=item.url,
        seller_id=item.seller_id,
        is_authenticated=item.is_authenticated,
    )


async def _reject_foreign_urls(report, session: AsyncSession, user: User) -> None:
    """CSV에 이미 존재하는 남의 URL이 들어오면 해당 행을 저장 대상에서 제외한다."""
    if not report.items:
        return

    urls = [item.url for item in report.items]
    rows = (
        await session.execute(
            select(ItemRecord.url, ItemRecord.source, ItemRecord.seller_id).where(
                ItemRecord.url.in_(urls)
            )
        )
    ).all()

    mine = user.seller_id
    foreign = {
        url
        for url, source, seller_id in rows
        if not owns_item(
            account_seller_id=mine,
            item_source=source,
            item_seller_id=seller_id,
        )
    }

    if not foreign:
        return

    kept = []
    for item in report.items:
        if item.url in foreign:
            report.skipped += 1
            report.accepted -= 1
            if len(report.errors) < 50:
                report.errors.append(
                    f"다른 출처 또는 다른 판매자의 매물이라 수정할 수 없습니다: {item.url}"
                )
        else:
            kept.append(item)

    report.items = kept


@router.get(
    "/items",
    response_model=ListingListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listMyUploadedItems",
    summary="내 직접등록 매물 (기업고객 전용)",
    responses={
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "기업고객 계정만 사용할 수 있습니다."},
        409: {"description": "계정에 판매자가 올바르게 연결되어 있지 않습니다."},
    },
)
async def list_my_uploaded_items(
    user: Annotated[User, Depends(require_role("client"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    search: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """현재 로그인한 판매자의 직접등록 매물만 반환한다."""
    await _require_client_seller(session, user)

    conditions = [
        ItemRecord.source == UPLOAD,
        ItemRecord.seller_id == user.seller_id,
        ItemRecord.is_active.is_(True),
        ItemRecord.is_usable.is_(True),
    ]
    query = search.strip()
    if query:
        conditions.append(ItemRecord.title.ilike(f"%{query}%"))

    total = (
        await session.execute(
            select(func.count()).select_from(ItemRecord).where(*conditions)
        )
    ).scalar_one()

    posted = func.coalesce(ItemRecord.posted_at, ItemRecord.first_seen_at)
    rows = (
        (
            await session.execute(
                select(ItemRecord)
                .where(*conditions)
                .order_by(posted.desc(), ItemRecord.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return ListingListResponse(
        total=total,
        count=len(rows),
        limit=limit,
        offset=offset,
        has_next=offset + len(rows) < total,
        items=[_to_listing(row) for row in rows],
    )


@router.post(
    "/csv",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    operation_id="uploadCsv",
    summary="매물 CSV 업로드 (기업고객 전용)",
    responses={
        400: {"description": "CSV를 해석할 수 없습니다."},
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "기업고객 계정만 사용할 수 있습니다."},
        409: {"description": "계정에 판매자가 올바르게 연결되어 있지 않습니다."},
        413: {"description": "파일이 너무 큽니다."},
        503: {"description": "DB에 쓸 수 없는 상태입니다. 잠시 후 다시 시도하세요."},
    },
)
async def upload_csv(
    request: Request,
    user: Annotated[User, Depends(require_role("client"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """CSV 본문을 받아 직접등록 매물로 저장하고 현재 client 판매자와 연결한다."""
    raw = await _read_body_capped(request, MAX_UPLOAD_BYTES)

    if not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="빈 파일입니다.",
        )

    report = parse_csv(raw)

    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            await _require_client_seller(session, user)
            await _reject_foreign_urls(report, session, user)
    except HTTPException:
        raise
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        logger.warning("CSV 업로드 실패 (소유/판매자 확인): %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": "30"},
        ) from exc

    if report.accepted == 0:
        detail = report.errors[0] if report.errors else (
            f"저장할 행이 없습니다. 첫 줄에 {', '.join(REQUIRED_COLUMNS)} 이 있어야 합니다."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    urls = [item.url for item in report.items]

    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            saved = await repository.upsert_items(
                report.items, session=session, commit=False
            )

            await session.execute(
                update(ItemRecord)
                .where(ItemRecord.url.in_(urls), ItemRecord.source == UPLOAD)
                .values(seller_id=user.seller_id)
            )
            await session.commit()

            hidden = (
                (
                    await session.execute(
                        select(ItemRecord.title)
                        .where(
                            ItemRecord.url.in_(urls),
                            ItemRecord.is_usable.is_(False),
                        )
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )

            visible = (
                await session.execute(
                    select(func.count())
                    .select_from(ItemRecord)
                    .where(
                        ItemRecord.url.in_(urls),
                        ItemRecord.is_usable.is_(True),
                        ItemRecord.is_active.is_(True),
                        ItemRecord.seller_id == user.seller_id,
                    )
                )
            ).scalar_one()
    except HTTPException:
        raise
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        await session.rollback()
        logger.warning("CSV 업로드 실패 (쓰기 경로): %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": "30"},
        ) from exc

    logger.info(
        "CSV 업로드: %s(seller_id=%s)가 %d행 중 %d건 저장 (%d건 제외)",
        user.username,
        user.seller_id,
        report.total_rows,
        saved,
        report.skipped,
    )

    return UploadResponse(
        total_rows=report.total_rows,
        accepted=report.accepted,
        saved=saved,
        visible=visible,
        skipped=report.skipped,
        errors=report.errors,
        filtered=list(hidden),
    )


@router.put(
    "/items/{item_id}/image",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_200_OK,
    operation_id="uploadItemImage",
    summary="매물 사진 등록 (기업고객 전용)",
    responses={
        400: {"description": "이미지로 받아들일 수 없는 파일입니다."},
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "기업고객이 등록한 매물만 수정할 수 있습니다."},
        404: {"description": "해당 매물을 찾을 수 없습니다."},
        409: {"description": "계정에 판매자가 올바르게 연결되어 있지 않습니다."},
        413: {"description": "파일이 너무 큽니다."},
        503: {"description": "DB 또는 저장소에 쓸 수 없는 상태입니다."},
    },
)
async def upload_item_image(
    item_id: int,
    request: Request,
    user: Annotated[User, Depends(require_role("client"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """현재 client 판매자가 소유한 직접등록 매물의 사진을 교체한다."""
    raw = await _read_body_capped(request, MAX_IMAGE_BYTES)

    await _require_client_seller(session, user)

    item = await _load_my_item(session, user, item_id)

    try:
        safe = sanitize_image(raw)
    except ImageRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    previous = item.image_url

    try:
        object_name = await asyncio.to_thread(
            save_image,
            safe.data,
            safe.extension,
        )
    except StorageUnavailable as exc:
        logger.warning("매물 %s 사진 저장소 실패: %s", item_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 사진을 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": "30"},
        ) from exc

    item.image_url = public_url(object_name)

    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            await session.commit()
    except (TimeoutError, SQLAlchemyError) as exc:
        await session.rollback()
        await asyncio.to_thread(delete_image, object_name)

        logger.warning(
            "매물 %s 사진 DB 저장 실패: %s: %s",
            item_id,
            type(exc).__name__,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    prev_name = object_name_from_url(previous)
    if prev_name:
        await asyncio.to_thread(delete_image, prev_name)

    logger.info(
        "매물 %s 사진 등록: %dx%d, %d바이트 (%s)",
        item_id,
        safe.width,
        safe.height,
        len(safe.data),
        user.username,
    )

    return ImageUploadResponse(
        item_id=item_id,
        image_url=item.image_url,
        width=safe.width,
        height=safe.height,
        bytes=len(safe.data),
    )


@router.delete(
    "/items/{item_id}",
    response_model=ItemDeleteResponse,
    status_code=status.HTTP_200_OK,
    operation_id="deleteMyUploadedItem",
    summary="내 매물 내리기 (기업고객 전용)",
    responses={
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "기업고객이 등록한 매물만 내릴 수 있습니다."},
        404: {"description": "해당 매물을 찾을 수 없습니다."},
        409: {"description": "계정에 판매자가 올바르게 연결되어 있지 않습니다."},
        503: {"description": "DB 에 쓸 수 없는 상태입니다."},
    },
)
async def delete_my_uploaded_item(
    item_id: int,
    user: Annotated[User, Depends(require_role("client"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    현재 client 판매자가 소유한 직접등록 매물을 화면에서 내린다.

    **행을 지우지 않는다.** is_active=False 로 바꾸면 공개 목록과 '내 매물'
    질의가 모두 그 매물을 제외한다. 행을 남기는 이유는 url 유니크 키 때문이다 —
    같은 매물을 CSV 로 다시 올리면 새 행이 생기는 대신 이 행이 되살아난다.

    사진도 S3 에 남긴다. 되살릴 때 사진까지 다시 올려야 하는 상황을 만들지
    않으려는 것이다. 사진을 실제로 지우는 것은 사진 교체 때만 한다.
    """
    await _require_client_seller(session, user)

    item = await _load_my_item(session, user, item_id)
    title = item.clean_title or item.title

    if not item.is_active:
        # 이미 내려간 매물이다. 같은 결과를 돌려준다 — 화면이 두 번 눌렀을 때
        # 에러를 보여줄 이유가 없다(멱등).
        return ItemDeleteResponse(item_id=item_id, title=title)

    item.is_active = False
    await _commit_guarded(session, f"매물 {item_id} 내리기")

    logger.info("매물 %s 내림: %s (%s)", item_id, title, user.username)

    return ItemDeleteResponse(item_id=item_id, title=title)
