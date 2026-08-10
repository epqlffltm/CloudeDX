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

API 코드만 빠르게 고칠 땐 백그라운드 크롤러를 꺼둘 수 있다 (`ENABLE_CRAWLER`, 기본값 `true`).
`ENABLE_CRAWLER=true`(기본값)면 **서버가 요청을 받기 시작하기 전에 당근마켓 → 중고나라
크롤링을 한 바퀴 먼저 끝낸다** — 그래야 서버가 뜨자마자 `/crawled-items`에 데이터가 있다.
`--reload`는 파일을 고칠 때마다 프로세스를 통째로 재시작하는데, 그때마다 이 대기(수십 초)가
매번 다시 발생하니 API만 고칠 땐 꺼두는 걸 권장한다:

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
| GET | `/crawled-items` | 크롤러가 방금 모은 최신 결과. 쿼리: `source`(당근마켓/중고나라), `search`, `min_price`, `max_price`, `limit`, `offset` |

## 알아둘 점

- `/items`는 여전히 정적 CSV 스냅샷(`app/daangn_with_images.csv`)을 서빙한다. 처음 만들 때
  `dangun.py`로 한 번 긁어둔 고정 데이터라, 이후 크롤링 결과와는 무관하다.
- `/crawled-items`가 실제 백그라운드 크롤러 결과다. `scheduler.py`가 30분마다
  `data/crawled_items.json`(당근마켓), `data/joongna_crawled_items.json`(중고나라)을
  덮어쓰고, 이 라우터는 매 요청마다 그 파일을 새로 읽는다 — 캐싱을 안 하기 때문에
  서버를 껐다 켜지 않아도 최신 크롤링 결과가 바로 반영된다.
- 두 엔드포인트는 스키마도 다르다 (`Item`은 CSV 컬럼 그대로, `CrawledItemOut`은
  `CrawledItem`에 `source`/`is_sold`가 추가되고 `time`→`time_text`, `link`→`url`로
  이름이 다르다). 나중에 CSV 자체를 없애고 `/items`도 크롤러 데이터를 보게 통합할 수도
  있지만, 지금은 일부러 분리해뒀다.

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

이제 서버 시작 시 첫 크롤링을 끝까지 기다린 뒤에야 요청을 받기 시작하기 때문에
(`ENABLE_CRAWLER=true` 기준), `--reload`와는 어차피 궁합이 안 좋다 — 파일 하나만 고쳐도
프로세스가 통째로 재시작되면서 크롤링을 처음부터 다시 기다려야 한다. 그래서:

- **크롤러까지 포함해서 실제로 돌려볼 때**: `--reload` 없이 (`uv run uvicorn app.main:app`)
- **API 코드만 빠르게 고칠 때**: `--reload` + `ENABLE_CRAWLER=false`

## 알려진 이슈 / TODO

- `crawl_daangn_once()`/`crawl_joongna_once()`(scheduler.py)의 검색어가 각각 "아이폰",
  "구찌"로 하드코딩돼 있음. 위치 기반이라 검색어+지역 조합에 따라 결과가 0건일 수 있다
  (실제로 겪음: 마곡동 기준 "아이폰"은 0건, "냉장고"는 60건). 환경변수나 설정값으로
  분리하면 좋음.
- `CrawledItem`에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- Playwright는 실제 Chromium이 설치된 환경에서만 온전히 동작
  (컨테이너/CI 환경에서 돌리려면 `playwright install` 별도 실행 필요)

## 스택

FastAPI · Playwright · pandas · uv