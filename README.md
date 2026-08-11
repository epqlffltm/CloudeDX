# CloudeDX — 중고 명품 가방(여성) 조회 API

FastAPI로 중고 명품 가방(여성용) 매물을 조회하는 REST API. 백그라운드에서 당근마켓 ·
중고나라 크롤러가 구찌 · 에르메스 · 샤넬 · 루이비통을 브랜드별로 주기적으로 수집해서
PostgreSQL에 upsert하고, `/crawled-items` 라우터가 브랜드·가격 필터가 가능한 목록/단건
조회를 제공한다.

## 왜 사이트를 두 개 쓰는가 — 역할 분담

당근마켓과 중고나라는 겉보기엔 둘 다 "중고거래 사이트"지만 실제 쓰임새가 다르다.

- **당근마켓 = 동네 시세 참고용.** 당근은 애초에 동네 커뮤니티 마켓이라 위치 기반 반경
  검색이 핵심이고, 문화적으로도 직거래가 기본이다. "전국에서 제일 싼 가방"이 부산에
  있어봐야 서울 사는 사람은 못 사니, 여기서는 "내 동네에 지금 뭐가 올라와 있나"를
  보는 용도로 쓴다. 전국 커버리지를 시도하지 않고 자동감지된 위치 하나만 크롤링한다
  (지역 코드를 수천 개 순회하는 건 요청 폭증 + 봇 감지 위험 때문에 비현실적이기도 하다).
- **중고나라 = 전국 최저가 비교용.** 중고나라는 원래 택배거래 중심의 온라인 마켓이라
  위치가 의미 없다. 그래서 "구찌 가방 전국 최저가"라는 개념이 여기서는 실제로 성립한다.

`/crawled-items`의 `source` 필터로 이 둘을 구분해서 조회할 수 있다 — "내 동네에서 보기"는
`source=당근마켓`, "최저가 비교"는 `source=중고나라`로 프론트에서 나눠 보여주면 된다.

## 아키텍처

두 사이트 크롤러 모두 Playwright 기반 비동기로 통일했다. "브라우저 실행 → 스크롤 →
카드 링크 훑어서 텍스트/이미지 추출" 흐름은 `app/crawler/base.py`에 공용 엔진으로 두고,
사이트마다 다른 부분(URL 생성 · CSS 셀렉터 · 텍스트 파싱)만 `daangn/`, `joongna/`에서 구현한다.
검색어는 브랜드명 + "가방"을 자동으로 합쳐서 만든다 (`config.py`의 `query`/`keyword`
계산 프로퍼티). 크롤링 결과는 PostgreSQL(`app/db/`)에 upsert되고, `/crawled-items`는
그 DB를 직접 조회한다.

```
app/
├── main.py                      # FastAPI 진입점, lifespan에서 DB 테이블 준비 + 첫 크롤링 대기
├── crawler/
│   ├── base.py                   # 공용 엔진: 브라우저 실행, 스크롤, 카드 수집, JSON 저장
│   ├── brands.py                  # LUXURY_BRANDS = 구찌/에르메스/샤넬/루이비통
│   ├── models.py                   # CrawledItem (source: 사이트, brand: 브랜드)
│   ├── scheduler.py                 # 30분 주기, 사이트별로 브랜드 4개를 순회해서 DB에 upsert
│   ├── daangn/                       # 당근마켓 (Playwright)
│   │   ├── config.py                  # brand + keyword_suffix("가방") -> query
│   │   ├── parser.py                   # 카드 텍스트 파싱 (순수 함수, 브라우저 없이 테스트 가능)
│   │   ├── crawler.py                  # DaangnCrawler
│   │   ├── run.py                      # 단독 CLI (--brand 또는 --all-brands)
│   │   └── debug_cards.py               # 셀렉터 매칭/필터 통과 여부를 눈으로 확인하는 디버그 도구
│   └── joongna/                       # 중고나라 (Playwright)
│       ├── config.py                   # brand + keyword_suffix("가방") -> keyword
│       ├── parser.py
│       ├── crawler.py                  # JoongnaCrawler
│       └── run.py                      # 단독 CLI (--brand 또는 --all-brands)
├── db/
│   ├── models.py                  # SQLAlchemy ORM: ItemRecord (items 테이블)
│   ├── engine.py                   # 비동기 엔진, 세션 팩토리, init_db(), get_session()
│   └── repository.py                # upsert_items(): url 기준 insert-or-update
├── routers/
│   ├── items.py                   # /items 조회 엔드포인트 (정적 CSV)
│   └── crawled.py                  # /crawled-items 조회 엔드포인트 (DB)
├── data_loader.py                    # CSV 스냅샷(daangn_with_images.csv) 로딩 + 캐싱
├── schemas.py                         # Pydantic 응답 모델
└── daangn_with_images.csv              # 정적 CSV 스냅샷 ("샤넬 가방" 검색 결과, 최초 수집분)
```

## DB

로컬 PostgreSQL은 docker-compose로 띄운다:

```
docker compose up -d
```

접속 정보는 `DATABASE_URL` 환경변수로 받고, 기본값이 위 docker-compose 설정과 맞춰져
있어서 별도 설정 없이 그대로 동작한다:

```
postgresql+asyncpg://cloudedx:cloudedx@localhost:5432/cloudedx
```

서버가 뜰 때(`main.py`의 lifespan) `init_db()`가 테이블이 없으면 만든다 — 아직 스키마가
안정되지 않은 초기 단계라 Alembic 없이 `create_all()`로 시작했다. 스키마가 안정되면
Alembic 도입을 고려할 것 (TODO 참고).

**upsert 방식**: `items` 테이블은 `url`을 유니크 키로 쓴다. 크롤링할 때마다 같은 매물이면
가격/상태 등만 갱신하고 `last_seen_at`을 찍고(`first_seen_at`은 유지), 새 매물이면
새로 insert한다 (`app/db/repository.py`, PostgreSQL의 `INSERT ... ON CONFLICT DO UPDATE`).
JSON 파일 방식과 달리 "이 매물이 며칠째 안 팔리는지"를 나중에 `first_seen_at`/`last_seen_at`
차이로 볼 수 있다.

## 실행

```
uv sync
uv add playwright sqlalchemy asyncpg
uv run playwright install chromium
docker compose up -d
uv run uvicorn app.main:app --reload
```

Selenium/webdriver-manager는 더 이상 쓰지 않으니 정리해도 된다:

```
uv remove selenium webdriver-manager
```

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

API 코드만 빠르게 고칠 땐 백그라운드 크롤러를 꺼둘 수 있다 (`ENABLE_CRAWLER`, 기본값 `true`).
`ENABLE_CRAWLER=false`여도 DB 테이블 준비는 항상 하기 때문에, 이전에 크롤링해둔 데이터가
있으면 `/crawled-items`는 그대로 조회된다. `ENABLE_CRAWLER=true`(기본값)면 **서버가
요청을 받기 시작하기 전에 당근마켓 → 중고나라 크롤링을 한 바퀴 먼저 끝낸다** — 브랜드
4개를 사이트마다 순서대로 검색하기 때문에(검색 8회) 이 대기가 **수 분 단위**로 걸릴 수
있다. `--reload`는 파일을 고칠 때마다 프로세스를 통째로 재시작하는데, 그때마다 이 대기가
매번 다시 발생하니 API만 고칠 땐 꺼두는 걸 강력히 권장한다:

```
$env:ENABLE_CRAWLER="false"
uv run uvicorn app.main:app --reload
```

크롤러만 단독으로 돌리고 싶으면 (브랜드 하나 또는 전체, DB에도 upsert됨):

```
uv run python -m app.crawler.daangn.run --brand "샤넬" --show-browser
uv run python -m app.crawler.daangn.run --all-brands
uv run python -m app.crawler.joongna.run --brand "구찌" --pages 5 --show-browser
uv run python -m app.crawler.joongna.run --all-brands
```

셀렉터가 실제로 뭘 잡는지 눈으로 확인하고 싶으면:

```
uv run python -m app.crawler.daangn.debug_cards --query "냉장고"
```

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 헬스 체크 |
| GET | `/items` | 정적 CSV 매물 목록. 쿼리: `search`, `min_price`, `max_price`, `limit`, `offset` |
| GET | `/items/{item_id}` | 정적 CSV 매물 단건 조회 (CSV 행 번호 기준) |
| GET | `/crawled-items` | DB에 저장된 최신 크롤링 결과. 쿼리: `source`(당근마켓/중고나라), `brand`(구찌/에르메스/샤넬/루이비통), `search`, `min_price`, `max_price`, `limit`, `offset` |
| GET | `/crawled-items/{item_id}` | DB PK 기준 단건 조회 |

## 브랜드

`app/crawler/brands.py`의 `LUXURY_BRANDS`에 고정돼 있다:

```python
LUXURY_BRANDS = ("구찌", "에르메스", "샤넬", "루이비통")
```

브랜드를 추가/변경하고 싶으면 이 목록만 고치면 `scheduler.py`와 두 사이트 `run.py`의
`--all-brands`가 전부 그대로 반영한다. 브랜드가 늘어나는 만큼 한 라운드 소요 시간도
비례해서 늘어난다는 점은 감안해야 한다.

검색어는 `"{브랜드} 가방"`으로 자동 생성한다 (예: "샤넬 가방"). 브랜드명만 검색하면
신발·지갑·향수 같은 비-가방 상품도 섞여 들어와서 "가방"을 붙여 좁혔다. 다만 이건 검색
키워드 수준의 필터라 완벽하지 않다 — "여성용"이라는 조건은 코드로 강제하고 있지 않고,
중고나라의 `category=103`(여성 가방 카테고리로 추정)에만 의존한다. 당근마켓 쪽은
카테고리 파라미터를 안 쓰고 있어서, 남성용 가방이나 관련 액세서리가 섞여 들어올 수 있다.

## 알아둘 점

- `/items`는 여전히 정적 CSV 스냅샷(`app/daangn_with_images.csv`)을 서빙한다. 처음
  `dangun.py`로 "샤넬 가방"을 한 번 긁어둔 고정 데이터라 도메인은 지금과 맞지만,
  DB/크롤러와는 완전히 별개의 파이프라인이다.
- `/crawled-items`의 `id`는 이제 DB의 실제 PK라 영구적이다 (JSON 방식이었을 때는 요청마다
  순서대로 매겨지는 값이라 크롤링이 다시 돌면 바뀌었는데, 지금은 안 바뀐다).
- 두 엔드포인트는 스키마도 다르다 (`Item`은 CSV 컬럼 그대로, `CrawledItemOut`은
  `brand`/`source`/`is_sold`/`first_seen_at`/`last_seen_at`이 추가되고 `time`→`time_text`,
  `link`→`url`로 이름이 다르다).
- 크롤러는 `data/*.json`에도 계속 저장한다 (DB랑 이중 저장) — 디버깅/백업용으로 남겨뒀다.

## 트러블슈팅 — Windows에서 `--reload` + Playwright `NotImplementedError`

Windows에서 `uvicorn ... --reload`로 실행하면 `asyncio.create_subprocess_exec`가
`NotImplementedError`를 던진다. `--reload`는 "reloader process"와 별도의
"server process"를 띄우는데, 그 server process가 자기 이벤트 루프를 이미 만든 뒤에야
`app/main.py`가 로드된다. 그래서 `app/main.py`에 넣어둔 `ProactorEventLoopPolicy` 설정은
이미 만들어진 루프에 적용되지 않고, Playwright가 브라우저를 서브프로세스로 띄우려는
순간 (Selector 계열 루프는 Windows에서 서브프로세스를 지원하지 않아서) 바로 걸린다.

**확실한 해결책은 `--reload`를 빼는 것이다.**

```
uv run uvicorn app.main:app
```

서버 시작 시 첫 크롤링을 끝까지 기다린 뒤에야 요청을 받기 시작하기 때문에
(`ENABLE_CRAWLER=true` 기준), `--reload`와는 어차피 궁합이 안 좋다. 그래서:

- **크롤러까지 포함해서 실제로 돌려볼 때**: `--reload` 없이 (`uv run uvicorn app.main:app`)
- **API 코드만 빠르게 고칠 때**: `--reload` + `ENABLE_CRAWLER=false`

## 알려진 이슈 / TODO

- "여성용" 필터링이 검색 키워드/카테고리 코드에만 의존한다 (위 "브랜드" 섹션 참고). 남성
  라인 상품이 섞여 들어오면 제목 기반 후처리 필터 추가를 고려할 것.
- `CrawledItem`/`items` 테이블에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- 스키마가 안정되면 `create_all()` 대신 Alembic 마이그레이션 도입 고려
- 브랜드 4개 x 사이트 2개 = 검색 8회라 한 라운드가 오래 걸린다. 병렬화(사이트별로 동시
  실행)나 브랜드별 스케줄 분산을 고려할 수 있음.
- Playwright는 실제 Chromium이 설치된 환경에서만 온전히 동작
  (컨테이너/CI 환경에서 돌리려면 `playwright install` 별도 실행 필요)

## 스택

FastAPI · Playwright · PostgreSQL · SQLAlchemy(async) · pandas · uv
