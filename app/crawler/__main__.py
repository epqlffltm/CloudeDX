# app/crawler/__main__.py

"""
크롤러를 단독 프로세스로 실행하는 진입점.

    uv run python -m app.crawler

백엔드(app/main.py)와 분리해서 돌리기 위한 것이다. 나누는 이유는 셋이다.

1. 이미지 크기 — Playwright와 Chromium이 1GB를 넘는다. 백엔드가 그걸 지고 다닐
   이유가 없다.
2. 스케일 — 백엔드를 2대로 늘리면 두 대가 각자 크롤링을 돌린다. 같은 매물을 두 번
   긁고 사이트에는 요청이 두 배로 간다.
3. 비용 — 크롤러는 30분에 한 번 몇 분만 일한다. 상시 프로세스 대신 스케줄 태스크로
   띄우면 유휴 시간에 브라우저를 안 올린다.

백엔드에서 함께 돌리려면 ENABLE_CRAWLER=true로 두면 되고(로컬 개발 기본값),
분리 운영할 때는 백엔드 쪽을 false로 두고 이 진입점을 별도로 띄운다.
"""

import asyncio
import sys

from app.crawler.scheduler import crawler_loop
from app.db.engine import DATABASE_URL, mask_url, wait_for_db

if sys.platform == "win32":
    # Playwright가 브라우저를 서브프로세스로 띄우려면 Proactor 루프가 필요하다.
    # Selector 계열 루프는 Windows에서 서브프로세스를 지원하지 않는다.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def main() -> None:
    print(f"[crawler] DB 연결 확인 중... ({mask_url(DATABASE_URL)})")
    await wait_for_db()
    print("[crawler] DB 연결 확인 완료")

    try:
        await crawler_loop()
    except asyncio.CancelledError:
        # 컨테이너 종료 신호. 조용히 빠져나간다.
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[crawler] 종료합니다.")