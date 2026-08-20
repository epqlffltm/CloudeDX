# app/crawler/sources.py

"""
수집처(source) 문자열 상수.

daangn/crawler.py와 joongna/crawler.py가 CrawledItem.source에 넣는 값이자,
DB items.source 컬럼에 저장되고 필터 조건으로도 쓰이는 값이다. 문자열을 여러 곳에
흩어 두면 오타 하나로 필터가 조용히 0건이 되므로 여기 한 곳에 모은다.
"""

DAANGN = "당근마켓"
JOONGNA = "중고나라"

# 화면의 수집처 필터 순서. 동네 시세(당근) -> 전국 최저가(중고나라) 순.
BUNJANG = "번개장터"

SOURCES: tuple[str, ...] = (DAANGN, JOONGNA, BUNJANG)
