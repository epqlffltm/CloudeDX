# 시연 가이드

> README에서 분리한 상세 문서다. 전체 지도는 [README](../README.md)의 문서 목차 참고.

## 시연 철학

시드로 다 채워 놓고 "이미 들어가 있습니다"라고 말하지 않는다. **판매자만 미리 깔고,
매물과 사진은 무대에서 손으로 넣는 모습을 보여준다** — CSV 일괄 등록 25건, 사진
개별 등록. 등록 → 정제 → 목록 노출 → 판매자 시트까지가 한 흐름으로 보이게.

## 시연 전 준비 (한 번만)

```powershell
# 1. .env에 판매자 연결 지정 (client 계정 업로드 → 청담 명품관)
#    CLIENT_SELLER_ID=1

# 2. 전체 기동
docker compose up -d --build

# 3. 판매자만 시드 (매물 0건 — 매물은 시연 중에 넣는다)
docker compose exec backend python -m app.seed_demo --sellers-only
```

`--sellers-only`가 판매자 8명(매장 보유 5 + 온라인 전용 3)을 깐다. 멱등이라 여러 번
돌려도 중복되지 않고, 매장 사진 경로가 비어 있으면 채워 넣는다.

매장 사진: `web/img/sellers/`의 5개 파일(chungdam · myeongdong · haeundae · daegu ·
pangyo`.jpg`)이 판매자 시트에 나온다. 저장소의 파일은 생성 견본이므로 시연 전에
**같은 파일명으로 실사풍 이미지를 덮어쓴다** (코드·DB 수정 불필요, 새로고침이면 반영).
시연에서 실제로 열리는 시트는 청담 명품관뿐이라 급하면 chungdam.jpg 한 장이면 된다.

## 시연 순서

1. 메인(http://localhost:8000) — 햄버거 → 드로어에서 카테고리, Maisons 마퀴, 검색 결과의
   카테고리·브랜드·수집처 칩 필터
2. LOGIN → `client` 계정 → 헤더 버튼이 My Page로 바뀐 것 확인
3. 기업고객 포털 → CSV 일괄 등록 → `reverdi-demo-매물.csv` 업로드 → **25/25건 저장**
4. 내 매물에서 몇 건 골라 사진 등록 (준비된 사진 25장, 파일명 01~25 = CSV 행 순서)
5. 메인으로 → 직접등록 매물 카드 클릭 → **판매자 시트**: 매장 사진 · 대표 제품 ·
   약도 · 연락하기
6. 대문 레일 **인기 물품** 탭 — 방금 누른 카드가 앞으로 온 것 확인. 같은 카드를
   연타해도 한 번으로 세고(30분 버킷), 다른 브라우저(시크릿 창)에서 누르면 한 번 더
   센다. 직접등록 매물이 먼저, 모자라면 크롤링 매물이 채운다
7. `admin` 계정 → 관리자 콘솔: 대시보드 실측치 · API 모니터링(/metrics) · 메모

## 시연용 CSV 규칙

헤더는 정확히 `title,price,url,region,is_authenticated`. 행마다:

- **title에 브랜드명 + 품목 키워드 필수** — 업로드 정제가 제목으로 브랜드·카테고리를
  판정하므로, 키워드가 없으면 "대상 품목 아님"으로 걸러진다 (백/가방·시계·반지·
  목걸이·구두·코트 등)
- **url은 전부 달라야 한다** — 중복 판정 키. 같은 url은 덮어쓰기가 된다
- price에 쉼표가 있으면 큰따옴표로 감싼다: `"11,900,000원"`
- 인코딩은 UTF-8 (엑셀은 "CSV UTF-8" 형식으로 저장)
- region은 비워도 됨, is_authenticated는 빈칸 또는 `정품인증`

업로드 후 저장 건수가 행 수와 다르면 빠진 행의 제목에 품목 키워드가 없는 것이다.

## 왜 판매자 시트가 청담 명품관만 뜨나

의도된 결과다. 로그인 계정이 admin/client 둘뿐이고 계정↔판매자 정식 연결이 없어,
`CLIENT_SELLER_ID=1`이 "client 계정의 업로드는 전부 1번 판매자 것"으로 잇는다.
시트는 매물 카드로만 열리므로, 매물이 전부 청담 것인 이상 청담 시트만 열린다 —
"로그인한 기업고객 = 청담 명품관"이라는 시연 스토리로는 오히려 자연스럽다.
질문이 나오면: 정식 회원가입·업체별 계정은 확장 지점이다 (`app/auth.py` 설명 참고).

## `docker compose down -v` 후 복구

볼륨을 지우면 DB가 통째로 사라지므로 두 가지를 다시 해야 한다:

```powershell
docker compose exec db createdb -U cloudedx cloudedx_test   # pytest용 테스트 DB
docker compose exec backend python -m app.seed_demo --sellers-only
```

기동 직후 backend가 unhealthy면 `/ready` 응답을 본다 — `storage.ok`가 false면
업로드 볼륨 권한 문제다 ([API 문서](api.md)의 상태 확인 절 참고).
