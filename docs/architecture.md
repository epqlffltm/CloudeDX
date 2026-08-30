# 아키텍처

> README에서 분리한 상세 문서다. 전체 지도는 [README](../README.md)의 문서 목차 참고.

## 왜 사이트를 두 개 쓰는가 — 역할 분담

당근마켓과 중고나라는 겉보기엔 둘 다 "중고거래 사이트"지만 실제 쓰임새가 다르다.

- **당근마켓 = 동네 매물 탐색용.** 당근은 애초에 동네 커뮤니티 마켓이라 위치 기반 반경
  검색이 핵심이고, 문화적으로도 직거래가 기본이다. "전국에서 제일 싼 가방"이 부산에
  있어봐야 서울 사는 사람은 못 사니, 여기서는 "내 동네에 지금 뭐가 올라와 있나"를
  보는 용도로 쓴다. 전국 커버리지를 시도하지 않고 자동감지된 위치 하나만 크롤링한다
  (지역 코드를 수천 개 순회하는 건 요청 폭증 + 봇 감지 위험 때문에 비현실적이기도 하다).
- **중고나라 = 전국 최저가 비교용.** 중고나라는 원래 택배거래 중심의 온라인 마켓이라
  위치가 의미 없다. 그래서 "구찌 가방 전국 최저가"라는 개념이 여기서는 실제로 성립한다.

화면과 API 모두 `source` 필터로 이 둘을 구분한다 — "내 동네에서 보기"는 `당근마켓`,
"최저가 비교"는 `중고나라`.

## 아키텍처

두 사이트 크롤러 모두 Playwright 기반 비동기로 통일했다. "브라우저 실행 → 스크롤 →
카드 링크 훑어서 텍스트/이미지 추출" 흐름은 `app/crawler/base.py`에 공용 엔진으로 두고,
사이트마다 다른 부분(URL 생성 · CSS 셀렉터 · 텍스트 파싱)만 `daangn/`, `joongna/`에서
구현한다. 검색어는 브랜드명 + "가방"을 자동으로 합쳐서 만든다 (`config.py`의
`query`/`keyword` 계산 프로퍼티).

### 계층 분리

| 계층 | 위치 | 책임 |
|---|---|---|
| 요청 스키마 | `app/schemas/requests.py` | 쿼리 파라미터의 형태와 검증 규칙 |
| 라우터 | `app/routers/` | HTTP 관심사만 — 경로, 상태 코드, 404 처리 |
| 리포지토리 | `app/db/repository.py` | 실제 SQL, 정렬, 카운트, upsert |
| 응답 스키마 | `app/schemas/responses.py` | JSON API로 나가는 형태 |

요청 스키마는 `Annotated[CrawledItemFilterParams, Query()]`로 주입한다(FastAPI 0.115+).
필터가 늘어나도 라우터 시그니처가 길어지지 않고, `min_price > max_price` 같은 모순은
repository까지 내려가기 전에 422로 걸러진다. `/api/crawled-items`와 `/api/products`가
**이 모델 하나를 공유**하기 때문에 두 경로의 필터 동작이 갈라지지 않는다.

목록 조회에서 `count_items()`와 `list_items()`가 같은 `_apply_filters()`를 공유하는 것도
같은 이유다 — 조건이 어긋나면 `total`과 `items`가 서로 안 맞는 응답이 나간다.

```
app/
├── config.py                    # 환경 변수 설정 (load_dotenv를 호출하는 유일한 곳)
├── main.py                       # FastAPI 진입점, lifespan에서 DB 확인 + 크롤러 기동
├── domain/                      # 백엔드·크롤러가 함께 쓰는 어휘 (무거운 의존성 없음)
│   ├── brands.py                 # LUXURY_BRANDS = 구찌/에르메스/샤넬/루이비통
│   ├── listing_status.py          # 판매완료·예약중 표기 판정 (두 사이트 공용)
│   ├── collection.py               # 수집 결과 + '빠짐없이 봤는가' 신호
│   ├── sources.py                 # SOURCES = 당근마켓/중고나라
│   ├── models.py                   # CrawledItem
│   └── timeparse.py                 # '3시간 전' -> datetime
├── crawler/                     # Playwright가 필요한 것만
│   ├── runner.py                 # 라운드 실행 규칙: 주기 판단, 사이트 단위 실패 처리, 기록
│   ├── source_runner.py          # 사이트 내부 규칙: 브랜드/페이지 부분 실패 처리 (Playwright 무관)
│   ├── scheduler.py              # 실제 사이트 크롤러를 연결하고 DB에 upsert (CRAWL_JOBS)
│   ├── base.py                   # 공용 엔진: 브라우저 실행, 스크롤, 카드 수집
│   ├── __main__.py                  # 크롤러 단독 실행 진입점 (python -m app.crawler)
│   ├── daangn/                        # 당근마켓 (Playwright)
│   │   ├── config.py · parser.py · crawler.py · run.py · debug_cards.py
│   └── joongna/                       # 중고나라 (Playwright)
│       └── config.py · parser.py · crawler.py · run.py
├── db/
│   ├── models.py                  # SQLAlchemy ORM: ItemRecord, CrawlRun
│   ├── crawl_runs.py               # crawl_runs 접근: 라운드 기록/조회
│   ├── engine.py                   # 비동기 엔진, 세션 팩토리, wait_for_db, mask_url
│   ├── migrations.py                # 적용된 리비전 조회 (/ready가 사용)
│   └── repository.py                # items 테이블 접근 전담: 조회/카운트/배치 upsert
├── routers/
│   ├── health.py                  # /health, /ready — 운영용 상태 확인
│   ├── products.py                 # /api/products — 프론트 계약 어댑터
│   ├── memo.py                     # /api/admin/memo — 관리자 공용 메모 (파일 저장)
│   ├── crawled.py                  # /api/crawled-items — 매물 JSON API
│   └── meta.py                      # /api/meta — 필터 선택지/수집 현황
├── schemas/
│   ├── requests.py                # 쿼리 파라미터 모델 + 검증
│   └── responses.py                # JSON 응답 모델
├── templates/
│   ├── base.html                  # 공통 레이아웃 + 스타일
│   ├── list.html                   # 목록
│   ├── detail.html                  # 상세
│   └── not_found.html                # 없는 매물
└── tests/                         # pytest (실제 Postgres에 붙는다)
    ├── conftest.py                 # 픽스처: 마이그레이션, 세션, 클라이언트
    └── test_*.py
```


## 프로세스 구성

같은 소스에서 두 개의 실행 단위가 나온다.

| | 백엔드 | 크롤러 |
|---|---|---|
| 진입점 | `uvicorn app.main:app` | `python -m app.crawler` |
| 이미지 | `dockerfile.backend` (564MB) | `dockerfile.crawler` (3.59GB) |
| Playwright | **없음** | Chromium 포함 |
| 포트 | 8000 | 없음 |

나누는 이유는 셋이다. **이미지 크기** — 백엔드가 Chromium을 지고 다닐 이유가 없다.
**스케일** — 백엔드를 2대로 늘리면 두 대가 각자 크롤링을 돌려 사이트에 요청이 두 배로
간다. **비용** — 크롤러는 30분에 한 번 몇 분만 일하므로 스케줄 태스크로 띄우면
유휴 시간에 브라우저를 안 올린다.

로컬 개발에서는 나눌 필요가 없다. `ENABLE_CRAWLER=true`(기본값)면 백엔드 프로세스가
크롤러를 함께 돌린다.

### 패키지 경계

백엔드가 Playwright 없이 뜨려면 임포트 경로에 Playwright가 없어야 한다. 코드가
크롤러를 쓰지 않더라도 `import`는 먼저 실행되기 때문이다. 패키지를 이렇게 나눴다.

| 패키지 | 담는 것 | 임포트 규칙 |
|---|---|---|
| `app/domain/` | 양쪽이 쓰는 어휘 (브랜드, 수집처, `CrawledItem`, 시각 환산) | 순수 파이썬만. 무거운 의존성 금지 |
| `app/crawler/` | Playwright가 필요한 것 | 백엔드에서 최상단 임포트 금지 |
| `app/db/`, `app/routers/`, `app/schemas/` | 저장·서빙 | `domain`은 되고 `crawler`는 안 됨 |

`app/crawler/` 안에서도 실행 정책과 Playwright 구현을 분리한다.

- `runner.py` — **라운드 단위 규칙**. 사이트 작업들을 실행하고, 일부 사이트 실패는 기록만
  남기며 모든 사이트가 실패했을 때만 라운드를 실패로 처리한다.
- `source_runner.py` — **사이트 내부 규칙**. 브랜드/페이지 일부 실패를 허용하되 모든 시도가
  예외로 실패하면 상위 계층에 실패를 전달한다. 정상적인 0건은 성공으로 유지한다.
- `scheduler.py` — 실제 `DaangnCrawler`/`JoongnaCrawler`를 위 규칙에 연결하고 DB에 upsert한다.

`runner.py`와 `source_runner.py`는 Playwright를 임포트하지 않는다.

```python
# app/crawler/runner.py — 라운드 규칙
async def run_crawl_round(jobs: tuple[CrawlJob, ...]) -> int: ...

# app/crawler/source_runner.py — 사이트 내부 규칙
async def collect_brands(...): ...
async def collect_pages(...): ...

# app/crawler/scheduler.py — 실제 사이트 구현 연결
CRAWL_JOBS = (crawl_daangn_once, crawl_joongna_once)
```

나눈 이유는 둘이다. **테스트** — 실패 정책을 Playwright에 묶지 않아 CI에서 브라우저 없이
경계조건을 검증할 수 있다. **경계** — 규칙과 수단이 한 파일에 있으면 규칙만 쓰려 해도
Chromium이 딸려 온다.

여기에 더해 `main.py`는 크롤러를 `lifespan` 안에서 **지연 임포트**한다. 없으면 안내를
남기고 서버는 정상적으로 뜬다.

**규칙은 문서가 아니라 테스트가 지킨다.** `app/tests/test_layering.py`가 소스를 AST로
훑어서 `app/db`·`app/routers`·`app/schemas`·`app/domain`의 최상단 임포트에
`app.crawler`가 있으면 파일과 줄 번호를 짚어 실패시킨다. 사람은 잊지만 CI는 안 잊는다.

`app/config.py`가 `load_dotenv()`를 호출하는 유일한 곳이다. `app.*` 중 가장 먼저
임포트되므로 다른 모듈은 임포트 순서를 신경 쓸 필요가 없다.
