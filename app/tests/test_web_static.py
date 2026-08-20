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
    번들 자산이 서빙된다.

    프론트가 Vite 빌드 산출물로 바뀌면서 파일명에 해시가 붙는다
    (assets/index-XXXXXXXX.js). 파일명을 박아두면 빌드할 때마다 테스트가
    깨지므로, index.html이 참조하는 경로를 읽어서 그것을 요청한다.
    """
    html = (await client.get("/")).text
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)

    assert refs, "index.html이 번들 자산을 참조하지 않는다"

    for ref in refs:
        assert (await client.get(ref)).status_code == 200, ref


async def test_api_not_shadowed_by_mount(client, session):
    """mount("/")가 등록 라우트보다 뒤라 /api는 여전히 API다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    res = await client.get("/api/products")

    assert res.status_code == 200
    assert res.json()["total"] == 1


async def test_board_still_alive(client, session):
    """게시판은 리다이렉트 없이 /board 직행으로 남는다."""
    assert (await client.get("/board")).status_code == 200
