# CloudeDX — 중고거래 매물 조회 API

FastAPI로 중고거래 매물을 조회하는 REST API. 백그라운드에서 당근마켓 · 중고나라 크롤러가
주기적으로 매물을 수집하고, `/items` 라우터가 검색·가격 필터가 가능한 목록/단건 조회를 제공한다.

## 아키텍처

두 사이트 크롤러 모두 Playwright 기반 비동기로 통일했다. "브라우저 실행 → 스크롤 →
카드 링크 훑어서 텍스트/이미지 추출" 흐름은 `app/crawler/base.py`에 공용 엔진으로 두고,
사이트마다 다른 부분(URL 생성 · CSS 셀렉터 · 텍스트 파싱)만 `daangn/`, `joongna/`에서 구현한다.

```
app/
├── main.py                      # FastAPI 진입점, lifespan으로 크롤러 백그라운드 태스크 관리
├── crawler/
│   ├── base.py                   # 공용 엔진: 브라우저 실행, 스크롤, 카드 수집, JSON 저장
│   ├── models.py                  # CrawledItem (source 필드로 사이트 구분)
│   ├── scheduler.py                # 30분 주기, CRAWL_JOBS 목록을 순서대로 await
│   ├── daangn/                      # 당근마켓 (Playwright)
│   │   ├── config.py
│   │   ├── parser.py                 # 카드 텍스트 파싱 (순수 함수, 브라우저 없이 테스트 가능)
│   │   ├── crawler.py                 # DaangnCrawler
│   │   └── run.py                      # 단독 CLI
│   └── joongna/                      # 중고나라 (Playwright)
│       ├── config.py
│       ├── parser.py
│       ├── crawler.py                 # JoongnaCrawler
│       └── run.py
├── routers/
│   └── items.py                   # /items 조회 엔드포인트
├── data_loader.py                   # CSV 스냅샷(daangn_with_images.csv) 로딩 + 캐싱
├── schemas.py                        # Pydantic 응답 모델
└── daangn_with_images.csv             # 정적 CSV 스냅샷 (조회 API가 실제로 서빙하는 데이터)
```

## 실행

```
uv sync
uv add playwright
uv run playwright install chromium
uv run uvicorn app.main:app --reload
```

Selenium/webdriver-manager는 더 이상 쓰지 않으니 정리해도 된다:

```
uv remove selenium webdriver-manager
```

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

API 코드만 빠르게 고칠 땐 백그라운드 크롤러를 꺼둘 수 있다 (`ENABLE_CRAWLER`, 기본값 `true`):

```
$env:ENABLE_CRAWLER="false"
uv run uvicorn app.main:app --reload
```

크롤러만 단독으로 돌리고 싶으면:

```
uv run python -m app.crawler.daangn.run --query "아이폰"
uv run python -m app.crawler.joongna.run --keyword "구찌" --pages 5
```

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 헬스 체크 |
| GET | `/items` | 매물 목록. 쿼리: `search`, `min_price`, `max_price`, `limit`, `offset` |
| GET | `/items/{item_id}` | 매물 단건 조회 (CSV 행 번호 기준) |

## 알아둘 점 — 크롤러와 조회 API는 아직 분리된 파이프라인

- 백그라운드 크롤러(`scheduler.py`)는 30분마다 당근마켓 → 중고나라 순서로 크롤링해서
  각각 `data/crawled_items.json`, `data/joongna_crawled_items.json`에 저장한다.
- 반면 `/items` API가 실제로 서빙하는 데이터는 `app/data_loader.py`가 읽는 정적 스냅샷
  `app/daangn_with_images.csv` 하나뿐이다.
- 즉 두 크롤러가 계속 새 데이터를 모아도 API 응답에는 반영되지 않는다. 크롤러 출력(JSON)을
  서빙 데이터로 연결하는 작업이 남아있다.

## 트러블슈팅 — Windows에서 `--reload` + Playwright `NotImplementedError`

Windows에서 `uvicorn ... --reload`로 실행하면 `asyncio.create_subprocess_exec`가
`NotImplementedError`를 던지는 경우가 있다. Windows에서 서브프로세스 생성을 지원하는 건
`ProactorEventLoop`뿐인데, `--reload` 환경에서 `SelectorEventLoop`가 쓰이면서 나는
문제이고, Playwright는 브라우저를 서브프로세스로 띄우기 때문에 바로 걸린다.

`app/main.py`에서 Windows일 때 `asyncio.WindowsProactorEventLoopPolicy()`를 명시적으로
지정해서 우회했다. 그래도 재현되면 `--reload` 없이 실행하거나(`uv run uvicorn app.main:app`),
API 코드만 고칠 땐 위 `ENABLE_CRAWLER=false`로 크롤러 자체를 꺼두는 걸 권장한다 — 어차피
`--reload`는 파일 하나만 바뀌어도 프로세스를 통째로 재시작하기 때문에 떠 있던 브라우저도
같이 죽는다.

## 알려진 이슈 / TODO

- 크롤러 출력 → 서빙 데이터 파이프라인 연결 (위 항목)
- `CrawledItem`에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- Playwright는 실제 Chromium이 설치된 환경에서만 온전히 동작
  (컨테이너/CI 환경에서 돌리려면 `playwright install` 별도 실행 필요)

## 스택

FastAPI · Playwright · pandas · uv