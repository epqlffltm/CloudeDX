# app/domain/sources.py

"""
수집처(source) 문자열 상수.

각 사이트 크롤러가 CrawledItem.source에 넣는 값이자, DB items.source 컬럼에 저장되고
필터 조건으로도 쓰이는 값이다. 문자열을 여러 곳에 흩어 두면 오타 하나로 필터가 조용히
0건이 되므로 여기 한 곳에 모은다.

    당근마켓   crawler/daangn/    Playwright
    중고나라   crawler/joongna/   Playwright
    번개장터   crawler/bunjang/   공개 API (브라우저 없음)
"""

DAANGN = "당근마켓"
JOONGNA = "중고나라"
BUNJANG = "번개장터"

# 기업고객이 CSV로 올린 매물. 크롤링이 아니라 업로드 라우터를 거쳐 들어온다.
#
# 이 값은 정품 인증 뱃지(items.is_authenticated)의 전제조건이기도 하다 —
# 업로드 라우터가 require_role("client")를 통과한 요청에만 박기 때문에,
# source가 이 값이라는 것 자체가 "검증된 계정을 거쳤다"는 뜻이 된다.
# 그래서 repository가 뱃지를 켤 때 이 상수를 함께 본다.
UPLOAD = "직접등록"

# 화면의 수집처 필터 순서.
# 동네 시세(당근) -> 전국 최저가(중고나라) -> 전국 물량(번개장터) 순.
SOURCES: tuple[str, ...] = (DAANGN, JOONGNA, BUNJANG, UPLOAD)
