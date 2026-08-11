# CloudeDX — 중고 명품 가방(여성) 수집 게시판

당근마켓 · 중고나라에서 중고 명품 가방(여성용) 매물을 주기적으로 수집해 PostgreSQL에
쌓고, 그 결과를 게시판 화면과 REST API로 보여주는 FastAPI 프로젝트. 브랜드는 구찌 ·
에르메스 · 샤넬 · 루이비통 네 개를 대상으로 한다.

파이프라인은 하나다:

```
크롤러(Playwright) → items 테이블(upsert) → 서빙
                                              ├─ /board          게시판 화면 (Jinja2)
                                              └─ /crawled-items  JSON API
```

두 서빙 경로는 같은 `app/db/repository.py`를 통해 조회한다. 화면과 API가 서로 다른
쿼리를 쓰기 시작하면 "API로는 나오는데 화면엔 없는" 상황이 생기기 때문이다.

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
├── main.py                      # FastAPI 진입점, .env 로딩, lifespan에서 DB 준비 + 첫 크롤링
├── crawler/
│   ├── base.py                   # 공용 엔진: 브라우저 실행, 스크롤, 카드 수집, JSON 저장
│   ├── brands.py                  # LUXURY_BRANDS = 구찌/에르메스/샤넬/루이비통
│   ├── sources.py                  # SOURCES = 당근마켓/중고나라 (source 문자열 상수)
│   ├── models.py                    # CrawledItem
│   ├── scheduler.py                  # 30분 주기, 사이트별로 브랜드를 순회해서 DB에 upsert
│   ├── daangn/                        # 당근마켓 (Playwright)
│   │   ├── config.py · parser.py · crawler.py · run.py · debug_cards.py
│   └── joongna/                       # 중고나라 (Playwright)
│       └── config.py · parser.py · crawler.py · run.py
├── db/
│   ├── models.py                  # SQLAlchemy ORM: ItemRecord (items 테이블)
│   ├── engine.py                   # 비동기 엔진, 세션 팩토리, init_db(재시도 포함)
│   └── repository.py                # items 테이블 접근 전담: 조회/카운트/배치 upsert
├── routers/
│   ├── web.py                     # /board — 게시판 화면 (목록 → 상세)
│   └── crawled.py                  # /crawled-items — JSON API
├── schemas/
│   ├── requests.py                # 쿼리 파라미터 모델 + 검증
│   └── responses.py                # JSON 응답 모델
└── templates/
    ├── base.html                  # 공통 레이아웃 + 스타일
    ├── list.html                   # 목록
    ├── detail.html                  # 상세
    └── not_found.html                # 없는 매물
```

## 화면

`/board`가 목록, 제목을 누르면 `/board/{id}` 상세로 들어간다.

필터는 자바스크립트 없는 GET form이라, 필터를 건 상태의 주소가 그대로 공유 가능한
링크가 된다. 페이지 이동 링크도 현재 쿼리스트링을 유지한 채 `offset`만 바꾸므로
3페이지에서 검색어가 풀리지 않는다.

목록 각 행에는 **관측 기간 막대**가 붙는다. `last_seen_at - first_seen_at`으로 계산한
"우리가 이 매물을 며칠째 보고 있는지"이고, 2주를 최대치로 잡는다. `first_seen_at`을
upsert 갱신 대상에서 제외한 설계 덕분에 만들 수 있는 값이며, 안 팔리고 오래 걸려 있는
매물을 훑어보며 찾는 것이 목적이다.

"등록 후 며칠"이 아니라 "우리가 처음 본 뒤 며칠"이라는 점은 화면에서도 관측 기준으로
표기한다 — 크롤링을 시작하기 전에 올라온 매물은 실제 등록일을 알 수 없다.

상세 화면에는 **상품 설명 본문이 없다.** 현재 크롤러가 검색 결과의 카드 목록만 훑기
때문이다. 본문을 채우려면 개별 매물 페이지를 한 번 더 방문하는 2단계 수집이 필요하고,
그때까지는 원본 링크로 안내한다 (TODO 참고).

게시판은 시연용이다. 나중에 프론트엔드를 따로 붙이면 `app/routers/web.py`와
`app/templates/`만 걷어내면 되고, `/crawled-items`는 그대로 남는다.

## 환경 변수

프로젝트 루트의 `.env`를 읽는다. `.env.example`을 복사해서 시작하면 된다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx` | DB 접속 정보 |
| `DB_PORT` | `5432` | docker-compose가 호스트에 열 포트. 5432가 이미 점유돼 있으면 여기만 바꾼다 |
| `ENABLE_CRAWLER` | `true` | `false`면 백그라운드 크롤러를 돌리지 않는다 |

`.env` 로딩은 `main.py` 최상단의 `load_dotenv()`가 담당하며, **`app.*` 임포트보다 먼저**
실행돼야 한다. `app.db.engine`이 모듈을 읽어들이는 시점에 `os.getenv`로 `DATABASE_URL`을
확정하기 때문에, 순서가 뒤바뀌면 `.env`를 읽어도 이미 늦어 기본값이 박힌다. 그래서 해당
임포트에는 `# noqa: E402`가 붙어 있다 — 린터가 정렬한다고 위로 올리면 안 된다.

`DATABASE_URL`에 `localhost` 대신 `127.0.0.1`을 쓰는 이유: Windows + Docker Desktop
조합에서 `localhost`가 IPv6(`::1`)로 먼저 풀리는데 포트 포워딩은 IPv4만 열려 있어
연결이 거부되는 경우가 있다.

## DB

로컬 PostgreSQL은 docker-compose로 띄운다:

```
docker compose up -d
```

서버가 뜰 때(`main.py`의 lifespan) `init_db()`가 테이블이 없으면 만든다 — 아직 스키마가
안정되지 않은 초기 단계라 Alembic 없이 `create_all()`로 시작했다. 컨테이너가 완전히
기동되기 전에 앱이 먼저 붙는 경우가 있어서, 연결 계열 오류(`OSError`)에 한해 2초 간격으로
5회까지 재시도한다. 비밀번호 오류나 SQL 오류는 기다려도 해결되지 않으므로 즉시 올린다.

> **주의**: `create_all()`은 **없는 테이블만 만든다.** 이미 있는 테이블의 구조는 바꾸지
> 않는다. `app/db/models.py`에 컬럼을 추가하면 서버는 멀쩡히 뜨는데 쿼리에서 터진다.
> 지금 단계에서는 `docker compose down -v`로 볼륨째 지우고 다시 올리면 된다.
> 데이터를 살려야 하는 시점이 오면 Alembic을 도입해야 한다 (TODO 참고).

**upsert 방식**: `items` 테이블은 `url`을 유니크 키로 쓴다. 같은 매물이면 가격/상태 등만
갱신하고 `last_seen_at`을 찍고, 새 매물이면 insert한다 (PostgreSQL의
`INSERT ... ON CONFLICT DO UPDATE`).

`first_seen_at`을 갱신 대상에서 뺀 것이 이 설계의 핵심이다. 여기를 같이 덮어쓰면 최초
발견 시점이 사라져서 체류 기간을 계산할 수 없게 되고, 게시판의 관측 기간 막대도 의미를
잃는다.

**배치 처리**: 한 라운드에서 브랜드별로 검색하다 보면 같은 매물이 여러 검색 결과에 걸린다.
그대로 한 INSERT 문에 넣으면 Postgres가 `ON CONFLICT DO UPDATE command cannot affect
row a second time` 에러를 낸다. 그래서 `_dedupe_by_url()`로 url 기준 중복을 먼저 제거한
뒤 500건씩 묶어서 보낸다. 건별로 보내면 건수만큼 왕복이 생긴다.

**정렬**: `last_seen_at DESC, id DESC`. `id`를 2차 정렬에 넣은 이유는 같은 크롤링 라운드에서
들어온 행들의 `last_seen_at`이 사실상 동일해서, 그것만으로는 정렬 순서가 요청마다 달라질
수 있기 때문이다. 그러면 페이지를 넘길 때 같은 매물이 두 번 보이거나 아예 건너뛰어진다.

## 실행

```
uv sync
uv run playwright install chromium
copy .env.example .env
docker compose up -d
uv run uvicorn app.main:app
```

- 게시판: http://127.0.0.1:8000/board
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

화면/API 코드만 빠르게 고칠 땐 백그라운드 크롤러를 꺼둘 수 있다 (`.env`에서
`ENABLE_CRAWLER=false`). 크롤러를 끄더라도 DB 테이블 준비는 항상 하기 때문에, 이전에
수집해둔 데이터가 있으면 게시판과 API 모두 정상적으로 조회된다.

`ENABLE_CRAWLER=true`(기본값)면 **서버가 요청을 받기 시작하기 전에 당근마켓 → 중고나라
크롤링을 한 바퀴 먼저 끝낸다** — 브랜드 4개를 사이트마다 순서대로 검색하기 때문에(검색
8회) 이 대기가 **수 분 단위**로 걸릴 수 있다.

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
| GET | `/health` | 프로세스 상태 확인 (DB는 확인하지 않음) |
| GET | `/board` | 게시판 목록 화면 |
| GET | `/board/{item_id}` | 게시판 상세 화면 |
| GET | `/crawled-items` | 매물 목록 JSON |
| GET | `/crawled-items/{item_id}` | 매물 단건 JSON |

목록의 쿼리 파라미터는 게시판과 API가 동일하다: `source`, `brand`, `search`, `is_sold`,
`min_price`, `max_price`, `limit`(1~100), `offset`.

목록 응답 형태:

```json
{
  "total": 137,
  "count": 20,
  "limit": 20,
  "offset": 0,
  "items": [...]
}
```

`total`은 필터 조건에 맞는 전체 건수, `count`는 이번 응답에 실제로 담긴 건수다.
다음 페이지 존재 여부는 `offset + count < total`로 판단하면 된다.

## 브랜드

`app/crawler/brands.py`의 `LUXURY_BRANDS`에 고정돼 있다:

```python
LUXURY_BRANDS = ("구찌", "에르메스", "샤넬", "루이비통")
```

이 목록만 고치면 `scheduler.py`, 두 사이트 `run.py`의 `--all-brands`, 게시판의 브랜드
선택 상자가 전부 그대로 반영한다. 브랜드가 늘어나는 만큼 한 라운드 소요 시간도 비례해서
늘어난다는 점은 감안해야 한다.

수집처 문자열도 같은 이유로 `app/crawler/sources.py`에 모아 뒀다. 문자열을 여러 곳에
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
- 크롤러는 `data/*.json`에도 계속 저장한다 (DB랑 이중 저장) — 디버깅/백업용이다.

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
- "여성용" 필터링이 검색 키워드/카테고리 코드에만 의존한다. 남성 라인 상품이 섞여
  들어오면 제목 기반 후처리 필터 추가를 고려할 것.
- 가격 변동 이력이 남지 않는다. 지금 구조는 최신 가격만 덮어쓰기라 "3일 전엔 200만원,
  지금은 150만원" 같은 추적이 불가능하다. 필요하면 `item_price_history` 테이블을 두고
  값이 바뀔 때만 insert하는 방식을 고려할 것.
- `CrawledItem`/`items` 테이블에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- 스키마가 안정되면 `create_all()` 대신 Alembic 마이그레이션 도입 고려
- 브랜드 4개 x 사이트 2개 = 검색 8회라 한 라운드가 오래 걸린다. 병렬화나 브랜드별
  스케줄 분산을 고려할 수 있음.
- lifespan이 첫 크롤링을 끝낼 때까지 서버를 열지 않아서, 수 분간 `/health`조차 응답하지
  못한다. 배포를 염두에 둔다면 첫 라운드도 백그라운드 태스크로 빼는 편이 낫다.
- 게시판 스타일이 `base.html` 안에 인라인으로 들어가 있다. 시연용으로 정적 파일 마운트
  없이 돌리려는 선택이고, 프론트를 분리하면 통째로 버릴 코드다.
- Playwright는 실제 Chromium이 설치된 환경에서만 온전히 동작
  (컨테이너/CI 환경에서 돌리려면 `playwright install` 별도 실행 필요)

## 스택

FastAPI · Jinja2 · Playwright · PostgreSQL · SQLAlchemy(async) · uv
