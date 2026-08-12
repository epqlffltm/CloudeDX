# CloudeDX — 중고 명품 가방(여성) 수집 게시판

당근마켓 · 중고나라에서 중고 명품 가방(여성용) 매물을 주기적으로 수집해 PostgreSQL에
쌓고, 그 결과를 게시판 화면과 REST API로 보여주는 FastAPI 프로젝트. 브랜드는 구찌 ·
에르메스 · 샤넬 · 루이비통 네 개를 대상으로 한다.

파이프라인은 하나다:

```
크롤러(Playwright) → items 테이블(upsert) → 서빙
                                              ├─ /board  게시판 화면 (Jinja2, 시연용)
                                              └─ /api    JSON API (프론트엔드용)
```

세 서빙 경로는 같은 `app/db/repository.py`를 통해 조회한다. 화면과 API가 서로 다른
쿼리를 쓰기 시작하면 "API로는 나오는데 화면엔 없는" 상황이 생기기 때문이다.

## 현재 상태

| | |
|---|---|
| 실행 단위 | 백엔드(564MB) · 크롤러(3.59GB) 두 이미지, compose 4개 서비스 |
| 스키마 | Alembic 마이그레이션 |
| 테스트 | 107개, 실제 Postgres 위에서 실행 |
| CI | GitHub Actions — lint · test · 이미지 빌드 |

한 번에 띄우려면:

```
copy .env.example .env
docker compose up -d --build
```

게시판 http://localhost:8000/board · 문서 http://localhost:8000/docs

로컬에서 코드를 고치며 개발하는 방법은 아래 "실행" 절을 참고한다.

## 왜 사이트를 두 개 쓰는가 — 역할 분담

당근마켓과 중고나라는 겉보기엔 둘 다 "중고거래 사이트"지만 실제 쓰임새가 다르다.

- **당근마켓 = 동네 시세 참고용.** 당근은 애초에 동네 커뮤니티 마켓이라 위치 기반 반경
  검색이 핵심이고, 문화적으로도 직거래가 기본이다. "전국에서 제일 싼 가방"이 부산에
  있어봐야 서울 사는 사람은 못 사니, 여기서는 "내 동네에 지금 뭐가 올라와 있나"를
  보는 용도로 쓴다. 전국 커버리지를 시도하지 않고 자동감지된 위치 하나만 크롤링한다
  (지역 코드를 수천 개 순회하는 건 요청 폭증 + 봇 감지 위험 때문에 비현실적이기도 하다).
- **중고나라 = 전국 최저가 비교용.** 중고나라는 원래 택배거래 중심의 온라인 마켓이라
  위치가 의미 없다. 그래서 "구찌 가방 전국 최저가"라는 개념이 여기서는 실제로 성립한다.

게시판과 API 모두 `source` 필터로 이 둘을 구분한다 — "내 동네에서 보기"는 `당근마켓`,
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
| 템플릿 | `app/templates/` | 게시판 화면 |

요청 스키마는 `Annotated[CrawledItemFilterParams, Query()]`로 주입한다(FastAPI 0.115+).
필터가 늘어나도 라우터 시그니처가 길어지지 않고, `min_price > max_price` 같은 모순은
repository까지 내려가기 전에 422로 걸러진다. **게시판과 JSON API가 이 모델 하나를
공유**하기 때문에 두 화면의 필터 동작이 갈라지지 않는다.

목록 조회에서 `count_items()`와 `list_items()`가 같은 `_apply_filters()`를 공유하는 것도
같은 이유다 — 조건이 어긋나면 `total`과 `items`가 서로 안 맞는 응답이 나간다.

```
app/
├── config.py                    # 환경 변수 설정 (load_dotenv를 호출하는 유일한 곳)
├── main.py                       # FastAPI 진입점, lifespan에서 DB 확인 + 크롤러 기동
├── domain/                      # 백엔드·크롤러가 함께 쓰는 어휘 (무거운 의존성 없음)
│   ├── brands.py                 # LUXURY_BRANDS = 구찌/에르메스/샤넬/루이비통
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
│   ├── web.py                      # /board — 게시판 화면 (목록 → 상세)
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

## 화면

`/board`가 목록, 제목을 누르면 `/board/{id}` 상세로 들어간다.

필터는 자바스크립트 없는 GET form이라, 필터를 건 상태의 주소가 그대로 공유 가능한
링크가 된다. 페이지 이동 링크도 현재 쿼리스트링을 유지한 채 `offset`만 바꾸므로
3페이지에서 검색어가 풀리지 않는다.

목록 각 행에는 **등록 후 경과 막대**가 붙는다. 원글이 올라온 시각(`posted_at`)부터
지금까지를 2주 최대치로 잡아 표시한다. 오래 걸려 있는 매물, 즉 가격 협상 여지가 있는
매물을 훑어보며 찾는 것이 목적이다.

제목은 우리 쪽 상세 화면으로, 각 행의 `원글 ↗`은 당근/중고나라 원본 게시글로 간다.
목록에서 바로 원본을 열고 싶은 경우와 우리 쪽 상세를 보려는 경우가 다르기 때문에
둘 다 둔다.

**등록 시각을 구하는 방법**은 아래 "등록 시각" 절에 정리했다. 값을 구하지 못한 매물은
`first_seen_at`(우리가 처음 본 시각)으로 대체하고, 대체했다는 사실을 "등록"이 아니라
"수집"이라고 표기하고 막대를 흐리게 해서 구분한다. 사이트가 시각을 표기하지 않은
경우인데, 수집 시각을 등록일인 것처럼 보여주면 실제보다 최근 글로 오해하게 된다.

## 등록 시각

두 사이트 모두 목록 카드에 절대 날짜를 안 쓰고 "3시간 전" 형태로만 보여준다. 개별
매물 페이지에 들어가면 정확한 날짜가 있을 수 있지만, 그러려면 매물 수만큼 페이지를 더
방문해야 한다. 그래서 목록에서 이미 얻은 문자열을 수집 시점 기준으로 환산해
`posted_at`에 저장한다 (`app/domain/timeparse.py`). 추가 요청이 0이다.

원문 표기는 `time_text` 컬럼에 그대로 남겨둔다 — 환산이 틀렸을 때 대조할 근거가 있어야
한다.

한계는 세 가지고, 전부 표기 방식 자체에서 온다:

- **정밀도**: "3시간 전"은 ±30분, "2달 전"은 ±보름 수준이다. 그래서 화면에서도 분
  단위로 단정하지 않고 상대 표기로 되돌려 보여준다 (정확한 값은 마우스를 올리면 나온다).
- **끌올**: 판매자가 글을 상단으로 올리면 당근은 "끌올 2일 전"으로 표기한다. 이건 끌올
  시각이지 최초 등록일이 아니라서, 끌올한 매물은 실제보다 최근 글로 잡힌다. 사이트가
  원래 등록일을 노출하지 않으므로 목록 수집만으로는 구분할 방법이 없다.
- **누락**: 중고나라는 카드에 시각 표기가 없는 경우가 있다. 그런 행은 `posted_at`이
  NULL이고 화면에서 수집 시각으로 대체된다.

상세 화면에는 **상품 설명 본문이 없다.** 현재 크롤러가 검색 결과의 카드 목록만 훑기
때문이다. 본문을 채우려면 개별 매물 페이지를 한 번 더 방문하는 2단계 수집이 필요하고,
그때까지는 원본 링크로 안내한다 (TODO 참고).

게시판은 시연용이다. 나중에 프론트엔드를 따로 붙이면 `app/routers/web.py`와
`app/templates/`만 걷어내면 되고, `/api` 아래는 그대로 남는다.

## 수집 동작

`app/crawler/runner.py`의 `crawler_loop()`가 백그라운드에서 돈다. `main.py`의
lifespan이 `create_task`로 띄우고 바로 요청을 받기 시작하므로 서버 시작을 막지 않는다.

**첫 라운드는 조건부로 즉시 실행한다.** `crawl_runs`의 마지막 기록을 보고, 주기보다
오래됐거나 기록이 없으면 바로 시작하고 최근이면 건너뛴다. 개발 중에는 서버를 하루에도
몇 번씩 재시작하는데 그때마다 검색 8회를 새로 도는 건 사이트에도 부담이고 봇 감지
위험도 올리기 때문이다.

`items.last_seen_at`이 아니라 `crawl_runs`를 보는 이유는 실패한 라운드도 세기
위해서다. 전부 실패한 라운드는 아무것도 저장하지 않아 `last_seen_at`이 갱신되지 않는데,
그러면 재시작할 때마다 곧바로 다시 긁으러 간다 — 봇 감지로 막힌 상황이라면 그게
제일 안 좋은 행동이다.

다른 프로세스가 수집 중(`running`)이면 양보한다. 배포 중에 크롤러 컨테이너가 잠깐
두 개가 되는 상황에서 중복 수집을 줄여준다.

**실패해도 루프는 죽지 않는다.** 실패 정책은 단계별로 나뉜다:

| 범위 | 처리 |
|---|---|
| 카드 하나 파싱 실패 | 해당 카드만 건너뜀 |
| 중고나라 페이지 하나 실패 | 다음 페이지 계속 |
| 브랜드 하나 실패 | 같은 사이트의 나머지 브랜드 계속 |
| 사이트 하나 실패 | 다른 사이트 계속, `last_error`에 기록하고 라운드는 성공으로 집계 |
| 모든 사이트 실패 | 라운드 실패로 처리하고 5분 뒤 재시도 (정상 주기 30분보다 짧게) |

성공/실패는 **수집 건수**가 아니라 **시도 자체가 정상 종료됐는지**로 판단한다.
정상적으로 페이지를 읽었지만 매물이 0건인 경우는 `SUCCESS / 0건`이 맞다. 반대로 한 브랜드의
모든 페이지가 예외로 실패하거나, 한 사이트의 모든 브랜드가 예외로 실패하면 상위 계층으로
예외를 올린다. 그래야 사이트가 전부 막힌 상태와 정말 매물이 없는 상태를 구분할 수 있다.

이 정책은 `app/crawler/source_runner.py`에서 Playwright와 분리해 구현한다. 따라서 실제
브라우저 없이도 전체 실패/부분 실패/정상 0건 경계조건을 CI에서 검증할 수 있다.

수집 결과는 `crawl_runs` 테이블에 기록되고 `/api/meta`로 노출된다.

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

### 이미지 빌드

```
docker build -f dockerfile.backend -t cloudedx-backend .
docker build -f dockerfile.crawler -t cloudedx-crawler .
```

실측 크기는 백엔드 **564MB**, 크롤러 **3.59GB**다. 6배 넘게 차이 나는 게 분리한 이유다.

Playwright는 optional dependency(`crawler` extra)라, 백엔드 이미지는 `uv sync`만,
크롤러 이미지는 `uv sync --extra crawler`를 쓴다. 로컬에서도 마찬가지다:

```
uv sync --extra crawler
```

`--extra crawler` 없이 `uv sync`를 치면 백엔드 이미지와 같은 구성이 된다 — 백엔드가
Playwright 없이 뜨는지 로컬에서 바로 확인할 수 있다.

### compose로 전체 띄우기

```
docker compose up -d --build
docker compose ps
```

네 개의 서비스가 순서대로 뜬다.

| 서비스 | 역할 | 기다리는 대상 |
|---|---|---|
| `db` | Postgres | — |
| `migrate` | `alembic upgrade head` 후 종료 | `db` healthy |
| `backend` | API + 게시판 | `migrate` 성공 종료 |
| `crawler` | 주기 수집 | `migrate` 성공 종료 |

**`migrate`를 별도 서비스로 둔 이유**는 백엔드를 2대로 늘렸을 때 두 대가 동시에 같은
마이그레이션을 돌리는 걸 막기 위해서다. `condition: service_completed_successfully`가
붙어 있어 마이그레이션이 실패하면 백엔드와 크롤러가 아예 뜨지 않는다 — 스키마가
준비되기 전에 트래픽을 받아 500을 뱉는 것보다 낫다.

백엔드 헬스체크는 `/health`가 아니라 **`/ready`**를 본다. compose에서는 이 상태가
다른 서비스의 대기 조건이 되므로, DB와 스키마까지 확인하는 쪽이 맞다.

크롤러에는 `shm_size: 1gb`가 붙어 있다. 컨테이너 기본 `/dev/shm`이 64MB뿐인데
Chromium은 탭마다 공유 메모리를 써서 페이지를 열다 죽는다.
`--disable-dev-shm-usage` 플래그로 우회할 수도 있지만 디스크를 대신 쓰게 되어 느려진다.

백엔드 컨테이너는 `ENABLE_CRAWLER=false`로 뜬다. 크롤러가 별도 컨테이너를 담당하므로
여기서 켜면 두 곳에서 동시에 긁게 되고, 애초에 그 이미지에는 Playwright가 없다.

로그와 상태 확인:

```
docker compose logs -f crawler
docker compose ps
curl http://localhost:8000/api/meta
```

`docker-compose.override.yml`은 로컬 개발용이다. compose가 자동으로 합쳐서 소스를
마운트하고 백엔드를 `--reload`로 띄운다. 배포 환경에서는 기본 파일만 쓴다:

```
docker compose -f docker-compose.yml up -d
```

## 환경 변수

프로젝트 루트의 `.env`를 읽는다. `.env.example`을 복사해서 시작하면 된다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx` | DB 접속 정보 |
| `DB_PORT` | `5432` | docker-compose가 호스트에 열 포트. 5432가 이미 점유돼 있으면 여기만 바꾼다 |
| `ENABLE_CRAWLER` | `true` | `false`면 백그라운드 크롤러를 돌리지 않는다 |
| `CRAWL_INTERVAL_MINUTES` | `30` | 수집 주기(분) |
| `CRAWL_RETRY_MINUTES` | `5` | 라운드가 통째로 실패했을 때 재시도까지 대기(분) |
| `JOONGNA_PAGES_PER_BRAND` | `3` | 중고나라 브랜드당 수집 페이지 수 |
| `CRAWL_RUN_TIMEOUT_MINUTES` | `60` | 이 시간을 넘겨 `running`으로 남은 기록은 죽은 것으로 본다 |
| `BACKEND_PORT` | `8000` | 백엔드 컨테이너를 호스트에 노출할 포트 |
| `TEST_DATABASE_URL` | `...@127.0.0.1:5432/cloudedx_test` | 테스트 전용 DB. 개발용과 분리해야 안전하다 |
| `ALLOWED_ORIGINS` | (비어 있음) | CORS 허용 출처. 쉼표로 구분. 비우면 미들웨어를 붙이지 않는다 |

compose로 띄울 때 `DATABASE_URL`은 `.env` 값이 아니라 compose가 주입하는
`postgresql+asyncpg://cloudedx:cloudedx@db:5432/cloudedx`가 쓰인다. 컨테이너끼리는
서비스 이름으로 통신하고, 호스트의 `DB_PORT` 매핑은 psql이나 DBeaver로 밖에서
들여다보기 위한 것이다.

`.env` 로딩은 `main.py` 최상단의 `load_dotenv()`가 담당하며, **`app.*` 임포트보다 먼저**
실행돼야 한다. `app.db.engine`이 모듈을 읽어들이는 시점에 `os.getenv`로 `DATABASE_URL`을
확정하기 때문에, 순서가 뒤바뀌면 `.env`를 읽어도 이미 늦어 기본값이 박힌다. 그래서 해당
임포트에는 `# noqa: E402`가 붙어 있다 — 린터가 정렬한다고 위로 올리면 안 된다.

`DATABASE_URL`에 `localhost` 대신 `127.0.0.1`을 쓰는 이유: Windows + Docker Desktop
조합에서 `localhost`가 IPv6(`::1`)로 먼저 풀리는데 포트 포워딩은 IPv4만 열려 있어
연결이 거부되는 경우가 있다.

접속 정보를 로그나 에러 메시지에 남길 때는 `mask_url()`을 거쳐 비밀번호를 가린다
(`postgresql+asyncpg://cloudedx:***@127.0.0.1:5432/cloudedx`). 컨테이너 로그는
CloudWatch 같은 곳에 그대로 쌓이고 접근 권한이 훨씬 넓기 때문이다. 호스트·포트·DB
이름은 남긴다 — 접속이 안 될 때 확인해야 하는 게 대부분 그쪽이라, 거기까지 가리면
로그를 봐도 원인을 못 찾는다.

## DB

로컬 PostgreSQL은 docker-compose로 띄운다:

```
docker compose up -d
```

스키마는 **Alembic이 관리한다.** 서버는 테이블을 만들지 않고, 뜰 때 DB가 응답하는지만
확인한다(`wait_for_db`). 컨테이너가 완전히 기동되기 전에 앱이 먼저 붙는 경우가 있어서,
연결 계열 오류(`OSError`)에 한해 2초 간격으로 5회까지 재시도한다. 비밀번호 오류는
기다려도 해결되지 않으므로 즉시 올린다.

### 마이그레이션

처음 받았거나 팀원이 새 마이그레이션을 푸시했으면:

```
uv run alembic upgrade head
```

**모델(`app/db/models.py`)을 고쳤다면 반드시:**

```
uv run alembic revision --autogenerate -m "설명"   # 초안 생성
# alembic/versions/ 에 생긴 파일을 읽어본다 ← 건너뛰지 말 것
uv run alembic upgrade head                        # 적용
```

생성된 파일을 확인하라고 강조하는 이유는 autogenerate가 완벽하지 않아서다. 특히
**컬럼 이름 변경을 "삭제 + 추가"로 만들어서 데이터를 날린다.** 그런 경우
`op.alter_column(..., new_column_name=...)`으로 직접 고쳐야 한다. NOT NULL 컬럼을
추가할 때도 기존 행이 있으면 실패하므로, nullable로 추가 → 값 채우기 → NOT NULL 변경
세 단계로 나눠야 한다.

```
uv run alembic current      # 지금 어느 리비전인지
uv run alembic history      # 전체 이력
uv run alembic downgrade -1 # 한 단계 되돌리기
```

마이그레이션은 앱 시작 시 자동 실행하지 않는다. 인스턴스를 여러 개 띄우면 동시에 같은
마이그레이션을 돌리려 들기 때문이다. 배포에서는 컨테이너 진입점이나 별도 태스크에서
한 번만 실행한다.

**제약조건 이름 규칙**을 `Base.metadata`의 `naming_convention`으로 못 박아 뒀다.
지정하지 않으면 DB가 알아서 이름을 붙이는데, 그 이름을 Alembic이 예측할 수 없어서
"이 제약을 삭제해라"는 마이그레이션이 실패하거나 환경마다 이름이 달라진다.

`alembic/env.py`는 기본 템플릿이 아니다. Alembic의 실행부는 동기 코드인데 이 프로젝트는
asyncpg를 쓰기 때문에, 비동기 엔진으로 접속한 뒤 `run_sync()`로 감싸 돌린다.
접속 정보도 `alembic.ini`가 아니라 `.env`의 `DATABASE_URL`에서 읽는다 — 설정 파일에
비밀번호를 박으면 그대로 커밋되기 때문이다.

### crawl_runs — 수집 상태

수집 라운드마다 한 행을 남긴다. `status`(running/success/failed), `started_at`,
`finished_at`, `item_count`, `error`.

프로세스 메모리가 아니라 DB에 두는 이유는 **크롤러와 백엔드가 별도 컨테이너로 갈라질
수 있기 때문이다.** 백엔드는 크롤러 프로세스의 메모리를 볼 수 없으니, DB를 거쳐야
`/api/meta`로 상태를 내려줄 수 있다. 덤으로 서버를 재시작해도 이력이 남고,
`_should_crawl_now()`가 다른 프로세스의 `running` 기록을 보고 양보할 수 있다.

일부 사이트만 실패한 라운드는 `status=success`에 `error`만 기록한다. 당근이 막혔어도
중고나라 결과는 들어왔으니 "수집이 아예 안 되는 상태"와 구분해야 한다.

**좀비 기록 처리**: 크롤러가 `SIGKILL`이나 전원 차단으로 죽으면 `finished_at`을 못
남긴다. 그 기록을 그대로 믿으면 `/api/meta`가 영원히 "수집 중"이라 답하고,
`_should_crawl_now()`는 영원히 다른 인스턴스가 돌고 있다고 착각해 수집이 멈춘다.
`CRAWL_RUN_TIMEOUT_MINUTES`(기본 60)를 넘긴 `running` 기록은 죽은 것으로 보고,
응답에 `stale: true`로 표시한다.

**upsert 방식**: `items` 테이블은 `url`을 유니크 키로 쓴다. 같은 매물이면 가격/상태 등만
갱신하고 `last_seen_at`을 찍고, 새 매물이면 insert한다 (PostgreSQL의
`INSERT ... ON CONFLICT DO UPDATE`).

`first_seen_at`을 갱신 대상에서 뺀 것이 이 설계의 핵심이다. 여기를 같이 덮어쓰면 최초
발견 시점이 사라져서, 등록 시각을 구하지 못한 매물의 대체 표기가 매 라운드마다 "방금"으로
초기화된다.

`posted_at`은 `COALESCE(items.posted_at, excluded.posted_at)`으로 처리한다. 상대 시각
표기는 시간이 지날수록 거칠어지기 때문이다 — 오늘 "3시간 전"이던 글은 내일 "1일 전"이
된다. 한 번 값을 구했으면 그때 환산한 것이 가장 정확하므로 유지하고, 아직 NULL인
행에만 새 값을 채운다. 덕분에 컬럼을 추가한 뒤 크롤링을 한 바퀴 돌리면 기존 행들도
자동으로 채워진다.

**배치 처리**: 한 라운드에서 브랜드별로 검색하다 보면 같은 매물이 여러 검색 결과에 걸린다.
그대로 한 INSERT 문에 넣으면 Postgres가 `ON CONFLICT DO UPDATE command cannot affect
row a second time` 에러를 낸다. 그래서 `_dedupe_by_url()`로 url 기준 중복을 먼저 제거한
뒤 500건씩 묶어서 보낸다. 건별로 보내면 건수만큼 왕복이 생긴다.

**정렬**: `COALESCE(posted_at, first_seen_at) DESC, id DESC` — 최근에 올라온 글이 위로
간다. `posted_at`이 NULL인 행을 `first_seen_at`으로 대체하지 않으면 그 행들이 전부 맨 뒤나
맨 앞으로 몰린다.

`id`를 2차 정렬에 넣은 이유는 "3일 전"으로 표기된 매물들의 환산 결과가 초 단위까지
같아질 수 있어서다. 그러면 정렬 순서가 요청마다 달라지고, 페이지를 넘길 때 같은 매물이
두 번 보이거나 아예 건너뛰어진다.

## 실행

컨테이너로 전부 띄우는 방법은 위 "compose로 전체 띄우기"에 있다. 여기는 코드를 고치며
개발할 때 쓰는 로컬 실행이다 — DB만 컨테이너로 띄우고 앱은 호스트에서 돌린다.

```
uv sync --extra crawler
uv run playwright install chromium
copy .env.example .env
docker compose up -d db          # DB만 띄운다
uv run alembic upgrade head
uv run uvicorn app.main:app
```

`docker compose up -d`(서비스 이름 없이)를 치면 백엔드·크롤러 컨테이너까지 함께 떠서
8000 포트가 겹치고 크롤러가 두 벌 돈다. 로컬 개발에서는 `db`만 지정한다.

- 게시판: http://127.0.0.1:8000/board
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

**서버는 크롤링을 기다리지 않고 바로 열린다.** DB 테이블 준비만 끝나면 요청을 받기
시작하고, 수집은 백그라운드 태스크로 돈다. 수집 전이면 목록이 비어 있을 뿐 게시판과
API는 정상 응답한다.

이 구조가 필요한 이유는 배포 환경 때문이다. ECS나 App Runner 같은 오케스트레이터는
헬스체크가 정해진 시간 안에 응답하지 않으면 컨테이너를 죽이고 다시 띄운다. 시작 시
수 분짜리 크롤링을 기다리면 서버가 뜨기도 전에 재시작되는 무한 루프에 빠진다.

브라우저를 계속 띄우는 게 부담되면 `.env`에서 `ENABLE_CRAWLER=false`로 꺼둘 수 있다.
꺼두더라도 DB 테이블 준비는 항상 하기 때문에, 이전에 수집해둔 데이터가 있으면 게시판과
API 모두 정상적으로 조회된다.

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
| GET | `/` | `/board`로 리다이렉트 |
| GET | `/health` | 프로세스 생존 확인 (liveness) |
| GET | `/ready` | 트래픽 수용 가능 여부 (readiness). 준비 안 됐으면 503 |
| GET | `/board` | 게시판 목록 화면 |
| GET | `/board/{item_id}` | 게시판 상세 화면 |
| GET | `/api/crawled-items` | 매물 목록 JSON |
| GET | `/api/crawled-items/{item_id}` | 매물 단건 JSON |
| GET | `/api/meta` | 필터 선택지(브랜드/수집처)와 수집 현황 |

`/api/meta`의 `crawler` 항목은 백그라운드 수집기의 상태다. 서버가 크롤링을 기다리지
않고 바로 열리기 때문에, 방금 뜬 서버는 목록이 비어 있다. 그게 "매물이 없다"인지
"아직 수집 중"인지 클라이언트가 구분할 수 있어야 해서 넣었다:

```json
{
  "crawler": {
    "is_running": true,
    "started_at": "2026-08-11T05:10:00Z",
    "last_finished_at": null,
    "last_item_count": null,
    "last_error": null,
    "rounds_completed": 0,
    "interval_minutes": 30
  }
}
```

`rounds_completed`가 0이면 아직 한 번도 성공하지 못했다는 뜻이다. `last_error`는
일부 사이트만 실패했을 때도 기록되므로, 값이 있다고 해서 수집이 멈춘 건 아니다.

목록의 쿼리 파라미터는 게시판과 API가 동일하다: `source`, `brand`, `search`, `is_sold`,
`min_price`, `max_price`, `limit`(1~100), `offset`.

응답의 `posted_at`은 원글 등록 시각이고, 구하지 못했으면 `null`이다. 원문 표기는
`time_text`에 그대로 들어 있다.

목록 응답 형태:

```json
{
  "total": 137,
  "count": 20,
  "limit": 20,
  "offset": 0,
  "has_next": true,
  "items": [...]
}
```

`total`은 필터 조건에 맞는 전체 건수, `count`는 이번 응답에 실제로 담긴 건수다.
`has_next`를 서버가 직접 내려주는 이유는 `offset + count < total` 규칙이 프론트 코드에
복사되는 걸 막기 위해서다 — 나중에 커서 기반으로 바꿔도 클라이언트는 그대로 둘 수 있다.

### 프론트엔드 연결

API는 `/api` 아래에 모여 있다. 화면 경로(`/board`)와 분리해 뒀기 때문에, 리버스
프록시에서 `/api`만 백엔드로 넘기거나 나중에 `/api/v2`를 병행하는 구성이 쉽다.

**CORS**: 프론트를 별도 개발 서버(Vite 5173 등)로 띄우면 브라우저가 다른 출처로 보고
요청을 막는다. `.env`의 `ALLOWED_ORIGINS`에 쉼표로 나열하면 열린다:

```
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

비워두면 미들웨어를 아예 붙이지 않는다 — 프론트가 없는 동안 불필요하게 열어두지 않기
위해서다. 조회 전용이라 `GET`만 허용한다.

**필터 선택지**: 브랜드·수집처 목록을 프론트에 하드코딩하지 말고 `/api/meta`에서 받아라.
`app/domain/brands.py`에 브랜드를 추가해도 프론트 코드는 그대로 둘 수 있다.

**타입 생성**: 각 엔드포인트에 `operation_id`를 명시해 뒀다(`listCrawledItems`,
`getCrawledItem`, `getMeta`). `http://127.0.0.1:8000/openapi.json`에서 스키마를 받아
클라이언트를 생성하면 이 이름이 함수명이 된다. 지정하지 않으면 경로를 바꿀 때마다
프론트의 함수 이름까지 따라 바뀐다.

**에러 형태**: 404 등은 FastAPI 기본인 `{"detail": "..."}`, 검증 실패(422)는
`{"detail": [{...}]}` 배열이다. 프론트에서 `detail`이 문자열인지 배열인지 구분해서
처리해야 한다.

## 상태 확인 — /health 와 /ready

목적이 다르다. 오케스트레이터(ECS, Kubernetes 등)가 서로 다른 판단에 쓰기 때문에
섞으면 안 된다.

| | 질문 | 실패하면 | 확인하는 것 |
|---|---|---|---|
| `/health` | 프로세스가 살아있나? | 컨테이너를 죽이고 재시작 | 아무것도 (프로세스 자체) |
| `/ready` | 트래픽을 받아도 되나? | 로드밸런서에서만 제외 | DB 연결 + 스키마 리비전 |

`/health`가 DB를 확인하지 않는 것은 의도적이다. DB가 잠깐 끊겼다고 앱을 재시작하는 건
상황을 악화시킬 뿐이고, DB가 돌아오면 앱은 알아서 회복한다.

`/ready`에 마이그레이션 검사를 넣은 이유는 배포 순서 때문이다. 새 코드를 올렸는데
`alembic upgrade`가 아직 안 돌았다면 그 인스턴스는 없는 컬럼을 조회하다 500을 뱉는다.
서버는 멀쩡히 떠 있으니 liveness는 통과하고, 결국 깨진 인스턴스로 트래픽이 흘러간다.

```json
{
  "ready": false,
  "database": { "connected": true, "error": null },
  "migration": {
    "current": null,
    "head": "862c742d32c6",
    "heads": ["862c742d32c6"],
    "up_to_date": false
  }
}
```

준비되지 않았을 때도 본문은 그대로 내려간다(상태 코드만 503). 무엇 때문에 실패했는지
알아야 조치할 수 있기 때문이다. `database.error`에는 예외 타입 이름만 담는다 —
메시지에는 접속 정보가 섞여 나올 수 있다.

## 브랜드

`app/domain/brands.py`의 `LUXURY_BRANDS`에 고정돼 있다:

```python
LUXURY_BRANDS = ("구찌", "에르메스", "샤넬", "루이비통")
```

이 목록만 고치면 `scheduler.py`, 두 사이트 `run.py`의 `--all-brands`, 게시판의 브랜드
선택 상자가 전부 그대로 반영한다. 브랜드가 늘어나는 만큼 한 라운드 소요 시간도 비례해서
늘어난다는 점은 감안해야 한다.

수집처 문자열도 같은 이유로 `app/domain/sources.py`에 모아 뒀다. 문자열을 여러 곳에
흩어 두면 오타 하나로 필터가 조용히 0건이 된다.

검색어는 `"{브랜드} 가방"`으로 자동 생성한다 (예: "샤넬 가방"). 브랜드명만 검색하면
신발·지갑·향수 같은 비-가방 상품도 섞여 들어와서 "가방"을 붙여 좁혔다. 다만 이건 검색
키워드 수준의 필터라 완벽하지 않다 — "여성용"이라는 조건은 코드로 강제하고 있지 않고,
중고나라의 `category=103`(여성 가방 카테고리로 추정)에만 의존한다. 당근마켓 쪽은
카테고리 파라미터를 안 쓰고 있어서, 남성용 가방이나 관련 액세서리가 섞여 들어올 수 있다.

## 알아둘 점

- 매물 `id`는 DB의 실제 PK다. 크롤링이 다시 돌아도 바뀌지 않으므로 상세 페이지 주소를
  공유해도 나중에 다른 글이 열리지 않는다.
- 가격은 화면에서 천 단위 구분으로 통일해 보여준다. 사이트마다 표기가 제각각이라
  ('4,000,000원', '400만원') 목록에서 세로로 정렬했을 때 읽기 나쁘기 때문이다. 파싱에
  실패했으면 원문을 그대로 두고, 그것도 없으면 "가격 미상"으로 표시한다.
- 가격 파싱에 실패한 매물(`price_value`가 `null`)은 가격 필터를 걸면 결과에서 제외된다.
  "가격 미상"을 조건에 맞다고 보면 최저가 비교가 오염되기 때문이다.
- **주기 실행 scheduler의 정본은 PostgreSQL 하나다.** 운영 수집 경로에서는 JSON 덤프를
  쓰지 않는다. 디버그 파일 쓰기 실패가 DB upsert까지 막는 결합을 피하기 위해서다.
  수동 실행용 CLI에서 필요한 경우에만 JSON을 저장할 수 있다.

## 테스트

```
uv sync --extra crawler
docker compose exec db createdb -U cloudedx cloudedx_test
uv run pytest
```

107개가 5~10초에 돈다. 접속 정보는 `.env`의 `TEST_DATABASE_URL`에서 읽고, 없으면
`cloudedx_test`를 기본값으로 쓴다 — **개발용 DB와 분리해야** 테스트가 데이터를 지워도
안전하다.

**실제 Postgres에 붙는다.** SQLite로 대체하지 않은 이유는 검증 대상 대부분이 Postgres
고유 동작이기 때문이다 — upsert의 `INSERT ... ON CONFLICT DO UPDATE`, `timestamptz`의
타임존 처리, `ilike`. SQLite에서 통과한 테스트가 운영에서 실패하면 테스트가 없느니만
못하다.

스키마는 `create_all`이 아니라 **`alembic upgrade head`로 만든다.** 그래야 마이그레이션
자체가 테스트 대상이 된다. 모델만 고치고 마이그레이션을 안 만들면 여기서 걸린다.

| 파일 | 대상 |
|---|---|
| `test_repository.py` | 필터, 정렬, 페이지네이션, upsert |
| `test_api.py` | 응답 계약, 422/404, 게시판 렌더링 |
| `test_runner.py` | 라운드 실행 규칙 — 사이트 실패 처리, 주기 판단, 루프 생존 |
| `test_source_runner.py` | 사이트 내부 실패 정책 — 전체/부분 실패, 정상 0건, 페이지 실패 |
| `test_crawl_runs.py` | 라운드 상태 전이, stale 판정 |
| `test_layering.py` | 패키지 경계 (백엔드가 크롤러를 임포트하지 않는지) |
| `test_timeparse.py` | 상대 시각 환산 |
| `test_health.py` | `/health`, `/ready` 분기 |
| `test_crawler_parser.py`, `test_joongna_parser.py` | 카드 텍스트 파싱 |

전부 브라우저 없이 돈다. `test_runner.py`는 사이트별 크롤러 대신 가짜 작업을 주입받고,
`test_source_runner.py`는 가짜 브랜드/페이지 수집 함수를 주입받는다. 따라서 Playwright를
설치하지 않은 test 잡에서도 라운드 규칙과 사이트 내부 실패 정책을 함께 검증할 수 있다.

특히 지키려는 것 여섯:

- `test_health_survives_database_outage` — DB가 죽어도 `/health`가 200을 유지하는지.
  깨지면 DB 장애가 전체 컨테이너 재시작 폭풍으로 번진다.
- `test_upsert_preserves_first_seen_at` — `_UPDATABLE_COLUMNS`에 실수로
  `first_seen_at`을 넣으면 걸린다.
- `test_pagination_does_not_repeat_or_skip` — `id` 2차 정렬을 빼면 실패한다.
- `test_backend_sees_crawler_state` — `crawl_runs` 테이블의 존재 이유 그 자체다.
- `test_backend_does_not_import_crawler` — 패키지 경계가 무너지면 백엔드 이미지가
  뜨지 않는다. 배포해서야 아는 것보다 여기서 걸리는 게 낫다.
- `test_collect_brands_zero_items_is_valid_success` / `test_collect_pages_all_fail_raises` —
  정상적인 검색 결과 0건과 실제 수집 장애를 혼동하지 않는지 검증한다.

### 픽스처가 앱의 전역 엔진을 쓰는 이유

`conftest.py`의 `session` 픽스처는 별도 엔진을 만들지 않고 `app.db.engine.engine`을
그대로 쓴 뒤 테스트마다 `dispose()`한다.

`upsert_items()`가 자체 세션을 만들 때 전역 엔진을 쓰기 때문이다. 테스트가 별도 엔진을
만들면 두 엔진이 공존하게 되고, pytest-asyncio가 테스트마다 새 이벤트 루프를 만드는
순간 풀에 남은 커넥션이 이전 루프에 묶여 `Task attached to a different loop` 오류가 난다.

같은 이유로 롤백 격리도 쓰지 않는다. `upsert_items()`가 직접 커밋하므로 바깥
트랜잭션으로 감싸도 격리되지 않아서, 매 테스트 시작에 `TRUNCATE`로 지운다.

## CI

`.github/workflows/ci.yml`. 푸시와 PR마다 돈다.

```
lint  ─┐
       ├─> build (backend, crawler 병렬)
test  ─┘
```

| 잡 | 하는 일 |
|---|---|
| `lint` | `ruff check .` (크롤러 코드까지 검사하므로 `--extra crawler`로 설치) |
| `test` | Postgres 서비스 컨테이너 → `alembic upgrade head` → `alembic check` → `pytest` |
| `build` | 이미지 두 개 빌드, 백엔드는 실제로 실행해 임포트 확인 |

설계상 노린 것 셋:

**test 잡은 `--extra crawler` 없이 설치한다.** 백엔드 이미지와 같은 구성이라, 백엔드
코드가 실수로 크롤러 모듈을 최상단에서 임포트하면 CI가 잡아낸다. 위 "임포트 사슬을
끊어 둔 것"을 지키는 장치다.

**`alembic check`을 넣었다.** 자동 생성할 것이 남아 있으면 실패한다. 모델을 고치고
마이그레이션을 만들지 않은 경우가 여기서 걸린다.

**build 잡이 백엔드 이미지를 실제로 실행한다.** `python -c "import app.main"`으로
Playwright 없이 임포트되는지 확인한다. 이미지가 빌드되는 것과 실행되는 것은 다르다.

## 트러블슈팅

### Windows에서 `--reload` + Playwright `NotImplementedError`

Windows에서 `uvicorn ... --reload`로 실행하면 `asyncio.create_subprocess_exec`가
`NotImplementedError`를 던진다. `--reload`는 "reloader process"와 별도의
"server process"를 띄우는데, 그 server process가 자기 이벤트 루프를 이미 만든 뒤에야
`app/main.py`가 로드된다. 그래서 `app/main.py`에 넣어둔 `ProactorEventLoopPolicy` 설정은
이미 만들어진 루프에 적용되지 않고, Playwright가 브라우저를 서브프로세스로 띄우려는
순간 (Selector 계열 루프는 Windows에서 서브프로세스를 지원하지 않아서) 바로 걸린다.

**확실한 해결책은 `--reload`를 빼는 것이다.**

- **크롤러까지 포함해서 실제로 돌려볼 때**: `--reload` 없이
- **화면/API만 빠르게 고칠 때**: `--reload` + `ENABLE_CRAWLER=false`

### `ConnectionRefusedError [WinError 1225]` — DB 연결 거부

`WinError 1225`는 TCP 레벨에서 즉시 거부된 것이다. 방화벽 드롭(타임아웃)도 인증 실패도
아니고, **해당 포트에 아무도 듣고 있지 않다**는 뜻이다.

```powershell
docker compose ps
```

`STATUS`가 healthy여도 안심하면 안 된다. **`PORTS` 열을 봐야 한다.**

- `0.0.0.0:5432->5432/tcp` — 정상
- `5432/tcp` (화살표 없음) — **포트가 호스트로 발행되지 않은 상태.** 컨테이너 안에서만
  Postgres가 돌고 있어서 헬스체크는 통과하지만 호스트에서는 못 붙는다.

포트 발행이 안 됐다면 원인을 가른다:

```powershell
docker run -d --name pgtest -p 5432:5432 -e POSTGRES_PASSWORD=test postgres:16
docker inspect -f "{{json .HostConfig.PortBindings}}" pgtest
docker inspect -f "{{json .NetworkSettings.Ports}}" pgtest
docker rm -f pgtest
```

- `PortBindings`에는 값이 있는데 `NetworkSettings.Ports`가 `{"5432/tcp":[]}`로 비어 있으면
  **Docker Desktop의 포트 프록시 문제다.** compose 파일이나 코드를 고쳐도 소용없다.
  `wsl --shutdown` 후 Docker Desktop을 트레이에서 Quit → 재시작. 그래도 안 되면 PC 재부팅.
- 둘 다 정상인데 접속이 안 되면 `DATABASE_URL`의 포트가 `DB_PORT`와 맞는지 확인한다.

### `port is already allocated`

5432를 이미 다른 것이 잡고 있다. 범인을 찾는다:

```powershell
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
netstat -ano | findstr :5432
```

다른 프로젝트의 Postgres 컨테이너면 정지시키거나, `.env`에 `DB_PORT=5433`을 넣고
`DATABASE_URL`의 포트도 같이 맞춘다.

> **compose가 실패했을 때는 `up -d`를 다시 치지 말고 `down` 먼저 해라.** 실패한 `up`은
> 컨테이너를 반쯤 만들어놓고 죽는데, 그다음 `up`은 그걸 다시 만드는 게 아니라 start만
> 한다. 그래서 "healthy인데 포트가 없는" 상태가 나온다.
> `docker compose down; docker compose up -d`를 습관으로 삼는 게 안전하다.

## 알려진 이슈 / TODO

- **상세 화면에 본문이 없다.** 목록 수집만 하고 있어서, 상품 설명·추가 이미지·판매자
  정보를 채우려면 2단계 수집이 필요하다. 목록에서 URL을 모으고 **새로 발견된 URL만**
  개별 페이지를 방문하면(이미 있는 `url`은 건너뜀) 두 번째 라운드부터 요청 수가 크게
  줄어든다. `items`에 `description`, `images`(JSONB) 컬럼 추가가 선행돼야 한다.
  이때 정확한 등록 날짜도 같이 가져올 수 있어서, 지금의 상대 시각 환산을 대체할 수 있다.
- 끌올한 매물과 새로 올라온 매물을 구분할 수 없다. `time_text`에 "끌올"이 붙어 있는지로
  최소한의 표시는 가능하니, 화면에 배지로 노출하는 것을 고려할 것.
- "여성용" 필터링이 검색 키워드/카테고리 코드에만 의존한다. 남성 라인 상품이 섞여
  들어오면 제목 기반 후처리 필터 추가를 고려할 것.
- 가격 변동 이력이 남지 않는다. 지금 구조는 최신 가격만 덮어쓰기라 "3일 전엔 200만원,
  지금은 150만원" 같은 추적이 불가능하다. 필요하면 `item_price_history` 테이블을 두고
  값이 바뀔 때만 insert하는 방식을 고려할 것.
- `CrawledItem`/`items` 테이블에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- 브랜드 4개 x 사이트 2개 = 검색 8회를 현재는 의도적으로 순차 실행한다. 외부 사이트에
  불필요한 동시 요청을 보내지 않는 쪽을 우선한 선택이다. 대상이 늘어 한 라운드 시간이
  운영 요구를 넘기면 bounded concurrency나 브랜드별 스케줄 분산을 고려할 수 있다.
- `_should_crawl_now()`의 중복 수집 억제는 진짜 잠금이 아니다. 두 프로세스가 동시에
  확인하면 둘 다 통과할 수 있다. 완전한 상호 배제가 필요해지면 Postgres 어드바이저리
  락으로 올려야 한다.
- `crawl_runs`가 계속 쌓인다. 30분 주기면 하루 48건, 1년에 1만7천 건이라 당장은 문제가
  없지만, 오래된 기록을 정리하는 작업이 언젠가 필요하다.
- 로그가 전부 `print`다. 배포하면 타임스탬프와 레벨이 있는 구조화 로그가 필요하다.
- 게시판 스타일이 `base.html` 안에 인라인으로 들어가 있다. 시연용으로 정적 파일 마운트
  없이 돌리려는 선택이고, 프론트를 분리하면 통째로 버릴 코드다.
- 브라우저 자체를 띄우는 E2E 크롤러 테스트는 실제 사이트에 의존해서 CI에서 돌리지 않는다.
  대신 파서, 라운드 정책(`test_runner.py`), 브랜드/페이지 실패 정책(`test_source_runner.py`)은
  브라우저 없이 검증한다. 향후 HTML 픽스처를 저장해 셀렉터까지 고정적으로 검증하는 방식을
  고려할 수 있다.
- CI가 이미지 빌드까지만 확인한다. compose 전체를 띄워 `/ready`가 200을 주는지까지
  보면 "문서대로 하면 돌아간다"가 보장되지만, 실행 시간이 늘어난다.

## 배포 전 남은 것

지금 상태로 컨테이너는 굴러가지만 실제 배포에는 몇 가지가 더 필요하다.

- **레지스트리 푸시**: CI가 이미지를 빌드만 하고 버린다. ECR에 올리는 단계를 붙여야 한다.
- **비밀 관리**: `DATABASE_URL`을 compose 파일에 평문으로 두고 있다. 배포에서는
  Secrets Manager나 SSM 파라미터로 주입해야 한다.
- **크롤러 실행 방식**: 상시 컨테이너 대신 EventBridge 스케줄 태스크로 띄우면 유휴
  시간에 브라우저를 안 올려 비용이 크게 준다. 그 경우 `crawler_loop()` 대신
  `run_crawl_round()`를 한 번만 실행하는 진입점이 필요하다.

## 스택

FastAPI · Jinja2 · Playwright · PostgreSQL · SQLAlchemy(async) · Alembic · pytest · Docker · GitHub Actions · uv