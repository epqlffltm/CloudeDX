# app/routers/uploads.py

"""
기업고객 전용 CSV 업로드.

파일을 multipart가 아니라 요청 본문(text/csv)으로 받는다. multipart를 쓰려면
python-multipart를 새로 넣어야 하는데, 파일이 하나뿐이고 함께 보낼 필드도 없어서
의존성과 uv.lock을 건드릴 만한 이유가 못 된다. 화면은 FileReader로 읽어 그대로
POST한다(web/js/client.js).

저장은 repository.upsert_items로 간다 — 크롤러와 같은 문이다. 제목 정제, 브랜드
판정, 카테고리 분류, url 기준 중복 처리가 업로드분에도 똑같이 걸린다. 별도 경로를
만들면 "크롤링한 샤넬"과 "올린 샤넬"의 표기가 갈라진다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/uploads/csv 다.
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_role
from app.config import MAX_UPLOAD_BYTES, WRITE_TIMEOUT_SECONDS
from app.db import repository
from app.db.engine import get_session
from app.db.models import ItemRecord
from app.domain.csv_import import REQUIRED_COLUMNS, parse_csv
from app.schemas.auth import UploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])


async def _read_body_capped(request: Request, limit: int) -> bytes:
    """
    본문을 읽되 limit 바이트를 넘기면 그 자리에서 중단한다.

    request.body() 는 전부 읽은 **뒤에** 길이를 알려준다. 그것을 재고 413을 돌려줘야
    소용이 없다 — 막으려던 수백 MB는 이미 메모리에 올라와 있다. 검사가 방어가 되려면
    읽는 도중에 끊어야 한다.

    Content-Length 를 먼저 보는 것만으로는 부족하다. chunked 전송에는 그 헤더가 없고,
    있더라도 클라이언트가 보내는 값이라 실제 본문과 일치한다는 보장이 없다. 헤더는
    빠른 거절용으로만 쓰고, 판단은 실제로 읽은 바이트로 한다.

    nginx client_max_body_size 가 있어도 이 검사는 필요하다. 배포 구성에서 nginx 를
    빼는 방향이고, 앱이 프록시 없이 뜨는 로컬·CI에는 애초에 그 방어가 없다.
    """
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
        413: {"description": "파일이 너무 큽니다."},
        503: {"description": "DB에 쓸 수 없는 상태입니다. 잠시 후 다시 시도하세요."},
    },
)
async def upload_csv(
    request: Request,
    user: Annotated[User, Depends(require_role("client"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    r"""
    CSV 본문을 받아 매물로 저장한다.

    첫 줄은 헤더이고 title, price, url이 반드시 있어야 한다. brand, image_url,
    region은 선택이다. 한글 헤더(제목/가격/링크/브랜드/이미지/지역)도 받는다.

    브랜드를 비워도 된다 — 제목에서 판정한다. 시트에 적힌 브랜드는 검색어 자리로만
    쓰이고, 화면에 뜨는 브랜드는 제목 판정 결과다. 사람이 적은 값보다 같은 규칙을
    거친 값이 목록 필터와 어긋나지 않는다.
    """
    raw = await _read_body_capped(request, MAX_UPLOAD_BYTES)

    if not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="빈 파일입니다.",
        )

    report = parse_csv(raw)

    # 유효한 행이 하나도 없으면 400이다. 200에 accepted=0을 담아 주면 화면이
    # 성공으로 그리고, 사용자는 아무 일도 안 일어난 이유를 모른다.
    if report.accepted == 0:
        detail = report.errors[0] if report.errors else (
            f"저장할 행이 없습니다. 첫 줄에 {', '.join(REQUIRED_COLUMNS)} 이 있어야 합니다."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # 저장됐다고 다 보이는 것이 아니다. 제목에서 브랜드나 카테고리를 판정하지
    # 못하면 정제 단계에서 is_usable=False가 되고 목록에서 빠진다(크롤링분과
    # 같은 규칙이다). "3건 저장"이라고 알려놓고 2건만 보이면 사용자는 원인을
    # 찾을 수 없으므로, 걸러진 것을 제목까지 붙여 돌려준다.
    urls = [item.url for item in report.items]

    # DB 작업 전체를 한 번에 시간 제한한다.
    #
    # 주 DB가 페일오버하는 60~120초 동안 이 요청은 어차피 성공할 수 없다. 제한이
    # 없으면 커넥션이 timeout 될 때까지 매달려 있고, 그동안 워커 하나를 붙잡는다.
    # 부하 테스트 중이라면 업로드 몇 건이 워커를 다 차지해서, 정작 살아 있는
    # 조회 경로까지 대기가 생긴다 — 읽기/쓰기를 나눈 의미가 없어진다.
    #
    # 빨리 실패하고 사용자에게 다시 시도하라고 말하는 편이 낫다.
    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            # 세션을 넘겨 커넥션을 한 번만 맺는다. 여기서 또 열면 DB가 죽어 있을 때
            # connect timeout 을 두 배로 기다린다(app/db/repository.py 설명 참고).
            saved = await repository.upsert_items(report.items, session=session)

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
                    )
                )
            ).scalar_one()
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        # 500이 아니라 503이다. 500은 "이 요청은 원래 안 되는 것"으로 읽히고,
        # 503 + Retry-After 는 "지금은 안 되니 잠시 후 다시"를 뜻한다. 페일오버는
        # 후자다. 지표에서도 앱 버그와 인프라 장애가 섞이지 않는다.
        logger.warning("CSV 업로드 실패 (쓰기 경로): %s", type(exc).__name__)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": "30"},
        ) from exc

    logger.info(
        "CSV 업로드: %s가 %d행 중 %d건 저장 (%d건 제외)",
        user.username,
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
