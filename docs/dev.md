# 개발 가이드

> README에서 분리한 상세 문서다. 전체 지도는 [README](../README.md)의 문서 목차 참고.

## 실행

컨테이너로 전부 띄우는 방법은 [배포 문서](deploy.md)의 "compose로 전체 띄우기"에 있다. 여기는 코드를 고치며
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

- 화면: http://127.0.0.1:8000/
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

**서버는 크롤링을 기다리지 않고 바로 열린다.** DB 테이블 준비만 끝나면 요청을 받기
시작하고, 수집은 백그라운드 태스크로 돈다. 수집 전이면 목록이 비어 있을 뿐 화면과
API는 정상 응답한다.

이 구조가 필요한 이유는 배포 환경 때문이다. ECS나 App Runner 같은 오케스트레이터는
헬스체크가 정해진 시간 안에 응답하지 않으면 컨테이너를 죽이고 다시 띄운다. 시작 시
수 분짜리 크롤링을 기다리면 서버가 뜨기도 전에 재시작되는 무한 루프에 빠진다.

브라우저를 계속 띄우는 게 부담되면 `.env`에서 `ENABLE_CRAWLER=false`로 꺼둘 수 있다.
꺼두더라도 DB 테이블 준비는 항상 하기 때문에, 이전에 수집해둔 데이터가 있으면 화면과
API 모두 정상적으로 조회된다.

크롤러를 단독 프로세스로 돌리려면:

```
uv run python -m app.crawler              # 주기 루프 (상시 컨테이너)
uv run python -m app.crawler --once       # 한 라운드만 돌고 종료
uv run python -m app.crawler --once --force   # 주기를 무시하고 즉시 수집
```

`--once`는 ECS 스케줄 태스크나 CronJob을 위한 것이다. 그런 환경은 "실행하고 끝나는"
프로세스를 전제하는데, 상시 루프를 넣으면 태스크가 영원히 끝나지 않아 스케줄러가 다음
실행을 겹쳐 띄우거나 타임아웃으로 죽인다. 종료 코드도 의미를 갖는다 — 실패를 0으로
끝내면 스케줄러는 성공으로 알고 알람을 울리지 않으므로, 라운드가 실패하면 1로 끝낸다.

`--force` 없이 `--once`를 쓰면 주기를 먼저 확인한다. 스케줄러가 실수로 촘촘히 띄우거나
재시도를 걸었을 때 사이트를 연달아 두드리지 않게 하려는 것이다.

특정 브랜드만 긁어보려면 (DB에도 upsert됨):

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


## 환경 변수

프로젝트 루트의 `.env`를 읽는다. `.env.example`을 복사해서 시작하면 된다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx` | DB 접속 정보 |
| `APP_ENV` | `local` | `production` 이면 비밀값 미설정 시 기동을 거부하고 쿠키에 Secure 를 붙인다 |
| `DATABASE_RO_URL` | (`DATABASE_URL`) | 읽기 복제본 주소. 비우면 주 DB로 떨어진다 |
| `READ_FALLBACK_COOLDOWN_SECONDS` | `30` | 복제본 접속 실패 후 주 DB로 보내는 시간 |
| `COOKIE_SECURE` | (`APP_ENV`) | 세션 쿠키 Secure 플래그. 로컬 HTTP에서는 꺼야 로그인이 된다 |
| `WRITE_TIMEOUT_SECONDS` | `15` | 쓰기 경로가 DB를 붙잡을 수 있는 최대 시간. 넘으면 503 |
| `DB_PORT` | `5432` | docker-compose가 호스트에 열 포트. 5432가 이미 점유돼 있으면 여기만 바꾼다 |
| `ENABLE_CRAWLER` | `true` | `false`면 백그라운드 크롤러를 돌리지 않는다 |
| `CRAWL_INTERVAL_MINUTES` | `30` | 수집 주기(분) |
| `CRAWL_RETRY_MINUTES` | `5` | 라운드가 통째로 실패했을 때 재시도까지 대기(분) |
| `JOONGNA_PAGES_PER_BRAND` | `3` | 중고나라 브랜드당 수집 페이지 수 |
| `CRAWL_RUN_TIMEOUT_MINUTES` | `60` | 이 시간을 넘겨 `running`으로 남은 기록은 죽은 것으로 본다 |
| `MISSING_THRESHOLD` | `3` | 몇 번 연속 미발견이면 비활성 처리할지 |
| `BACKEND_PORT` | `8000` | 백엔드 컨테이너를 호스트에 노출할 포트 |
| `TEST_DATABASE_URL` | `...@127.0.0.1:5432/cloudedx_test` | 테스트 전용 DB. 개발용과 분리해야 안전하다 |
| `BUNJANG_PAGES_PER_JOB` | `3` | 번개장터 검색 잡당 API 페이지 수 |
| `ALLOWED_ORIGINS` | (비어 있음) | CORS 허용 출처. 쉼표로 구분. 비우면 미들웨어를 붙이지 않는다 |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `LOG_FORMAT` | `text` | `json`이면 한 줄 JSON. 컨테이너 이미지는 `json`이 기본 |
| `POSTGRES_USER` | `cloudedx` | compose 가 db 초기화와 접속 문자열 조립에 함께 쓴다 |
| `POSTGRES_PASSWORD` | `cloudedx` | 위와 같음. 배포에서는 필수 |
| `POSTGRES_DB` | `cloudedx` | 위와 같음 |
| `SESSION_SECRET` | (프로세스마다 랜덤) | 세션 쿠키 서명 키. `APP_ENV=production` 이면 미설정 시 기동 거부 |
| `SESSION_MAX_AGE_SECONDS` | `43200` | 로그인 유지 시간(초). 기본 12시간 |
| `MAX_UPLOAD_BYTES` | `5242880` | CSV 업로드 최대 바이트 (ALB 는 본문 크기를 제한하지 않으므로 이 값이 유일한 상한이다) |
| `FORWARDED_ALLOW_IPS` | `*` (배포 `172.28.0.0/16`) | `X-Forwarded-For` 를 믿어줄 프록시 대역 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin1234` | 시연용 고정 계정 |
| `CLIENT_USERNAME` / `CLIENT_PASSWORD` | `client` / `client1234` | 시연용 고정 계정 |
| `CLIENT_SELLER_ID` | `0` (연결 안 함) | client 계정이 올린 매물을 연결할 판매자 id. 시연은 `1`(청담 명품관) — [웹 화면](frontend.md)의 판매자 시트 절 참고 |

`POSTGRES_*` 세 값은 **볼륨이 비어 있을 때(최초 기동)만** 반영된다. 이미 초기화된 뒤에
바꾸면 앱은 새 비밀번호로 접속하는데 DB 에는 옛 비밀번호가 남아 있어
`InvalidPasswordError` 가 난다. 바꾸려면 볼륨째 지운다: `docker compose down -v`.

숫자 설정은 1 미만이면 경고를 남기고 기본값으로 되돌린다. `CRAWL_INTERVAL_MINUTES=0`이면
크롤러가 쉬지 않고 사이트를 두드리고, `JOONGNA_PAGES_PER_BRAND=0`이면 "수집은 도는데
아무것도 안 쌓이는" 상태가 되는데 둘 다 며칠 뒤에야 알아챈다. 다만 오타 하나로 컨테이너가
부팅에 실패하는 것도 곤란해서 예외를 올리지는 않는다.

compose로 띄울 때 `DATABASE_URL`은 `.env` 값이 아니라 compose가 `POSTGRES_*` 로
조립한 주소가 쓰인다. 컨테이너끼리는 서비스 이름으로 통신하고(`@db:5432`), 호스트의
`DB_PORT` 매핑은 psql이나 DBeaver로 밖에서 들여다보기 위한 것이다.

조립은 YAML 앵커로 한 곳에서만 한다:

```yaml
x-db-env: &db-env
  DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-cloudedx}:...@db:5432/...

services:
  migrate:
    environment: *db-env          # 통째로 참조
  backend:
    environment:
      <<: *db-env                 # 병합 후 다른 값을 덧붙임
```

예전에는 같은 접속 문자열이 `migrate`·`backend`·`crawler` 세 곳에 복붙돼 있었다.
비밀번호를 바꾸려면 세 곳을 모두 고쳐야 했고, 하나를 빠뜨리면 **그 서비스만** 조용히
연결에 실패한다 — 나머지 둘은 멀쩡히 뜨기 때문에 원인을 찾기 어렵다. `db` 의
healthcheck 에 쓰는 사용자명도 같은 변수를 참조한다. 여기가 어긋나면 healthcheck 가
영영 통과하지 못하고 `depends_on` 에 걸린 서비스가 전부 기동하지 않는다.

`.env` 로딩은 **`app/config.py`** 가 담당한다. 이 모듈이 `load_dotenv()` 를 호출하는
유일한 곳이고 `app.*` 중 가장 먼저 임포트되므로, 다른 모듈은 "임포트 순서를 지켜야
`.env` 가 읽힌다"는 제약에서 자유롭다.

예전에는 `main.py` 최상단에서 `load_dotenv()` 를 부르고 그 아래 임포트마다
`# noqa: E402` 를 붙여야 했다. 린터가 정렬하면 조용히 깨지는 구조였다 — 순서가
뒤바뀌면 `.env` 를 읽어도 이미 늦어 기본값이 박힌다.

`DATABASE_URL`에 `localhost` 대신 `127.0.0.1`을 쓰는 이유: Windows + Docker Desktop
조합에서 `localhost`가 IPv6(`::1`)로 먼저 풀리는데 포트 포워딩은 IPv4만 열려 있어
연결이 거부되는 경우가 있다.

접속 정보를 로그나 에러 메시지에 남길 때는 `mask_url()`을 거쳐 비밀번호를 가린다
(`postgresql+asyncpg://cloudedx:***@127.0.0.1:5432/cloudedx`). 컨테이너 로그는
CloudWatch 같은 곳에 그대로 쌓이고 접근 권한이 훨씬 넓기 때문이다. 호스트·포트·DB
이름은 남긴다 — 접속이 안 될 때 확인해야 하는 게 대부분 그쪽이라, 거기까지 가리면
로그를 봐도 원인을 못 찾는다.


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

전부 5~10초에 돈다. 접속 정보는 `.env`의 `TEST_DATABASE_URL`에서 읽고, 없으면
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
| `test_api.py` | 응답 계약, 422/404 |
| `test_runner.py` | 라운드 실행 규칙 — 사이트 실패 처리, 주기 판단, 루프 생존 |
| `test_source_runner.py` | 사이트 내부 실패 정책 — 전체/부분 실패, 정상 0건, 페이지 실패 |
| `test_crawl_runs.py` | 라운드 상태 전이, stale 판정 |
| `test_lifecycle.py` | 매물 활성/비활성 전이, 범위 보호 |
| `test_parse_health.py` | 파싱 실패 측정과 완전성 전파 |
| `test_price_history.py` | 가격 변동 기록, 인하 목록 |
| `test_products.py` | 프론트 계약 어댑터 |
| `test_listing_status.py` | 판매완료 판정, 배지로 인한 제목 오염 방지 |
| `test_layering.py` | 패키지 경계 (백엔드가 크롤러를 임포트하지 않는지) |
| `test_config.py` | 설정 검증, 로그 형식 |
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
lint      ─┐
test      ─┼─> build (backend, crawler 병렬) ─> ECR 푸시 (main 에서만)
web-test  ─┘
```

| 잡 | 하는 일 |
|---|---|
| `lint` | `ruff check .` (크롤러 코드까지 검사하므로 `--extra crawler`로 설치) |
| `test` | Postgres 서비스 컨테이너 → `alembic upgrade head` → `alembic check` → `pytest` |
| `web-test` | Node 22 → `npm ci` → `npm run test:web` (web/test/smoke_home.mjs, jsdom) |
| `build` | 이미지 두 개 빌드(백엔드·크롤러) · 백엔드는 실행해 임포트 확인 |

`web-test`는 pytest가 보지 않는 `web/`을 지킨다. jsdom 위에서 home.js를 실제로
실행해 드로어·인기 탭·클릭 전송·판매자 시트가 API 응답으로 그려지는지 보고,
하나라도 FAIL이면 종료 코드 1로 잡이 빨간불이 된다. 로컬에서는 `npm i` 한 번 뒤
`npm run test:web`.

### ECR 푸시

main 브랜치 푸시에서만 올린다. PR 에서는 빌드와 스모크 테스트까지만 하고 레지스트리는
건드리지 않는다 — 포크에서 온 PR 은 OIDC 토큰을 받을 수 없기도 하다.

**인증은 OIDC 로 한다.** 장기 액세스 키를 Secrets 에 넣으면 유출됐을 때 회수 전까지
계속 유효하고, 로테이션을 사람이 기억해야 한다. OIDC 는 실행마다 단기 자격증명을
발급받으므로 저장소에 영구 비밀이 남지 않는다.

**태그는 커밋 해시 7자리와 `main` 을 함께 붙인다.** 해시 태그가 있으면 서버에 떠 있는
이미지가 어느 커밋인지 알 수 있고 롤백이 태그 교체로 끝난다. `main` 만 쓰면 "지금 뭐가
떠 있는지"를 알 수 없어 되돌릴 지점이 없다.

빌드 요약에 이미지 주소가 출력된다. Actions 실행 결과에서 복사해 서버의
`.env.web` / `.env.crawler` 에 붙이면 된다.

필요한 설정(인프라 담당):

| 항목 | 값 |
|---|---|
| ECR 리포지토리 | `reluxe-backend` · `reluxe-crawler` |
| OIDC 공급자 | `token.actions.githubusercontent.com` |
| IAM 역할 조건 | `repo:epqlffltm/CloudeDX:ref:refs/heads/main` |
| 저장소 Secret | `AWS_ROLE_ARN` |

### 설계상 노린 것 셋

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

### `[WinError 10013]` — 로컬 실행 시 포트 바인딩 거부

`netstat`에는 아무것도 안 잡히는데 바인딩만 거부된다면, Hyper-V/WSL2가 동적 포트
구간을 통째로 예약해서 그 안에 들어간 것이다.

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

목록에 해당 포트가 포함돼 있으면 예약 구간을 피해서 실행한다.

```powershell
uv run uvicorn app.main:app --port 5000
```

**`.env`의 `BACKEND_PORT`는 compose가 컨테이너 포트를 매핑할 때만 쓰인다.**
`uv run uvicorn`은 그 값을 읽지 않으므로 `--port`로 직접 줘야 한다.

이 예약 구간은 재부팅할 때마다 달라진다. DB(5432)도 같은 이유로 막힐 수 있고,
그때는 `.env`의 `DB_PORT`와 `DATABASE_URL`·`TEST_DATABASE_URL`의 포트를 함께 옮긴다.

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
- `category`가 아직 상수다. DB 기본값(`bag`)으로만 채워지고 크롤러는 이 컬럼을 모른다.
  두 번째 품목(시계 등)을 열 때 `CrawledItem`에 필드를 추가하고
  `_dedupe_by_url` → `_UPDATABLE_COLUMNS` 경로로 흘려야 한다.
- `CrawledItem`/`items` 테이블에 중고나라의 "무료배송" 여부에 대응하는 필드가 아직 없음
- 브랜드 4개 x 수집처 3개 = 검색 12회를 현재는 의도적으로 순차 실행한다. 외부 사이트에
  불필요한 동시 요청을 보내지 않는 쪽을 우선한 선택이다. 대상이 늘어 한 라운드 시간이
  운영 요구를 넘기면 bounded concurrency나 브랜드별 스케줄 분산을 고려할 수 있다.
- `_should_crawl_now()`의 중복 수집 억제는 진짜 잠금이 아니다. 두 프로세스가 동시에
  확인하면 둘 다 통과할 수 있다. 완전한 상호 배제가 필요해지면 Postgres 어드바이저리
  락으로 올려야 한다.
- **robots.txt를 확인하지 않는다.** [크롤러 문서](crawler.md)의 "수집 예절" 참고. 코드 결함이라기보다 프로젝트
  전제에 대한 미결 사항이다.
- User-Agent가 실행 환경과 일치하지 않는다. 봇임을 밝히는 UA로 바꾸면 정직해지지만
  차단 확률이 올라간다.
- `crawl_runs`가 계속 쌓인다. 30분 주기면 하루 48건, 1년에 1만7천 건이라 당장은 문제가
  없지만, 오래된 기록을 정리하는 작업이 언젠가 필요하다.
- 브라우저 자체를 띄우는 E2E 크롤러 테스트는 실제 사이트에 의존해서 CI에서 돌리지 않는다.
  대신 파서, 라운드 정책(`test_runner.py`), 브랜드/페이지 실패 정책(`test_source_runner.py`)은
  브라우저 없이 검증한다. 향후 HTML 픽스처를 저장해 셀렉터까지 고정적으로 검증하는 방식을
  고려할 수 있다.
- CI가 이미지 빌드까지만 확인한다. compose 전체를 띄워 `/ready`가 200을 주는지까지
  보면 "문서대로 하면 돌아간다"가 보장되지만, 실행 시간이 늘어난다.

## 시연용으로 단순화한 부분

포트폴리오 겸 시연용 프로젝트라 의도적으로 단순하게 둔 곳이 있다. 몰라서가 아니라
범위를 줄인 것이므로, 실서비스라면 어떻게 했을지를 함께 적어둔다.

| 지금 | 실서비스라면 |
|---|---|
| 계정 2개(`admin`/`client`)를 환경변수에 고정 | 사용자 테이블 + 해시 저장(PBKDF2·bcrypt), 회원가입/비밀번호 변경 |
| `SESSION_SECRET` 이 미설정 시 프로세스마다 랜덤 | 시크릿 매니저에서 주입, 주기적 로테이션 |
| 세션 = HMAC 서명 쿠키, 서버 측 저장 없음 | Redis 세션 스토어 또는 JWT + 토큰 버저닝(즉시 무효화 가능) |
| 단일 Postgres 컨테이너 | RDS(Multi-AZ), 백업·PITR |
| 크롤러 상시 컨테이너 | EventBridge 스케줄 태스크 — 유휴 시간에 브라우저를 안 올려 비용이 크게 준다. 진입점은 이미 있다: `python -m app.crawler --once` |
| 이미지를 로컬에서 빌드해 서버로 옮김 | CI 에서 레지스트리(GHCR·ECR)에 푸시하고 서버는 pull 만 |

계정을 DB 로 옮기지 않은 이유는 회원가입이 없고 계정이 둘뿐이라서다. 자세한 판단
근거는 `app/auth.py` 모듈 설명에 있다.
