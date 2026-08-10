# app/crawled_loader.py

"""
크롤러가 저장한 JSON 스냅샷(data/crawled_items.json, data/joongna_crawled_items.json)을
읽어서 API로 조회할 수 있게 해주는 모듈.

data_loader.py(CSV)와 달리 여기서는 lru_cache로 캐싱하지 않는다 — 백그라운드 크롤러가
30분마다 이 파일들을 덮어쓰는데, 캐싱하면 서버 재시작 전까지 계속 첫 크롤링 결과만
보여주게 되어 버린다. 파일이 크지 않아서 매 요청마다 새로 읽어도 부담 없다.
"""

import json
from pathlib import Path

DAANGN_JSON_PATH = Path("data/crawled_items.json")
JOONGNA_JSON_PATH = Path("data/joongna_crawled_items.json")


def _load_json(path: Path) -> list[dict]:
    """파일이 아직 없으면(크롤러가 한 번도 안 돌았으면) 빈 리스트를 반환."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_crawled_items() -> list[dict]:
    """
    당근마켓 + 중고나라 최신 크롤링 스냅샷을 합쳐서 반환.
    각 항목에 순서대로 id를 붙여서 단건 조회에 쓸 수 있게 한다.
    """
    items = _load_json(DAANGN_JSON_PATH) + _load_json(JOONGNA_JSON_PATH)

    for idx, item in enumerate(items):
        item["id"] = idx

    return items
