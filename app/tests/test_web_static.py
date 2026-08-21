# app/tests/test_web_static.py

"""
웹 화면 서빙(StaticFiles mount) 검증.

핵심은 두 가지다: 루트가 서비스 화면을 주는가, 그리고 mount가 맨 뒤라
등록된 라우트(/api, /board)를 가리지 않는가. 후자가 깨지면 화면은 뜨는데
API가 전부 404가 되는, 원인 찾기 고약한 장애가 된다.
"""

import re

from app.db import repository

from .test_products import make_item


async def test_root_serves_frontend(client):
    """루트가 게시판 리다이렉트가 아니라 Reverdi 서비스 화면(index.html)이다."""
    res = await client.get("/")

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Reverdi" in res.text
    assert "Re:Luxe" not in res.text
    assert ":Luxe" not in res.text


async def test_static_assets_served(client):
    """
    화면이 참조하는 자산이 실제로 서빙된다.

    프론트는 번들러를 거치지 않고 소스를 그대로 내보낸다. index.html이
    <script type="module" src="js/main.js"> 로 ES 모듈을 직접 부르고, 페이지마다
    필요한 스크립트(admin.js, login.js)만 로드하는 구조다.

    파일명을 테스트에 박아두면 프론트를 손볼 때마다 함께 깨지므로, index.html이
    실제로 참조하는 경로를 읽어서 그것을 요청한다. 참조는 상대 경로라 앞에
    슬래시를 붙여 mount 지점 기준으로 만든다.

    외부 호스트(폰트 CDN)와 SVG 내부 앵커(href="#i-crown")는 제외한다 — 서빙
    대상이 아니다.
    """
    html = (await client.get("/")).text

    refs = [
        ref
        for ref in re.findall(r'(?:src|href)="([^"]+)"', html)
        if not ref.startswith(("http://", "https://", "//", "#", "data:"))
        # href="./" 같은 자기 참조 링크는 자산이 아니다.
        and re.search(r"\.(css|js|mjs|svg|png|webp|ico)$", ref)
    ]

    assert refs, "index.html이 로컬 자산을 참조하지 않는다"

    for ref in refs:
        path = ref if ref.startswith("/") else f"/{ref}"
        assert (await client.get(path)).status_code == 200, path


async def test_module_entrypoint_is_served(client):
    """
    진입점 스크립트가 서빙된다.

    위 테스트는 "참조된 것이 전부 200"을 보지만, 참조가 하나도 없어도(정규식이
    아무것도 못 잡아도) 조용히 넘어갈 수 있는 구조는 아니다 — assert refs 가
    막는다. 다만 진입점만은 이름이 바뀌면 화면 전체가 죽으므로 따로 못 박는다.
    """
    res = await client.get("/js/main.js")

    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]


async def test_api_not_shadowed_by_mount(client, session):
    """mount("/")가 등록 라우트보다 뒤라 /api는 여전히 API다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    res = await client.get("/api/products")

    assert res.status_code == 200
    assert res.json()["total"] == 1


async def test_board_still_alive(client, session):
    """게시판은 리다이렉트 없이 /board 직행으로 남는다."""
    assert (await client.get("/board")).status_code == 200
