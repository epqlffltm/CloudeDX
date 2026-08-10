#app/data_loader.py
"""
당근마켓 크롤링 결과 CSV(daangn_with_images.csv, 프로젝트 루트에 위치)를 읽어
메모리에 캐싱하는 모듈. DB 없이 서빙하는 버전이라, 서버가 켜져 있는 동안
CSV는 딱 한 번만 읽고 이후 요청은 전부 메모리 캐시(lru_cache)를 사용한다.
"""

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).resolve().parent / "daangn_with_images.csv"


def _parse_price(price_str: str) -> int | None:
    """'4,000,000원' 같은 문자열에서 숫자만 뽑아 int로 변환. 실패하면 None."""
    if not isinstance(price_str, str):
        return None
    digits = re.sub(r"[^0-9]", "", price_str)
    return int(digits) if digits else None


@lru_cache(maxsize=1)
def load_items() -> list[dict]:
    """
    CSV를 읽어 dict 리스트로 반환.
    lru_cache 덕분에 프로세스가 살아있는 동안 실제 파일 읽기는 1회만 발생한다.
    CSV 내용을 바꿨다면 서버를 재시작해야 반영된다 (캐시 무효화 로직은 없음).
    """
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    df = df.fillna("정보없음")

    items = []
    for idx, row in df.iterrows():
        items.append(
            {
                "id": idx,
                "title": row["제목"],
                "price": row["가격"],
                "price_value": _parse_price(row["가격"]),
                "region": row["지역"],
                "time": row["시간"],
                "image_url": row["이미지링크"],
                "link": row["링크"],
            }
        )
    return items