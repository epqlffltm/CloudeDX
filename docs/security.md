# 보안

코드 동결(`ba01e85`) 이후 진행한 보안 점검의 결과다. "이미 돼 있던 것 / 고친 것 / 남긴 것 /
인프라에 넘긴 것" 네 묶음으로 적는다. 발표에서 "그럼 완벽하냐"는 질문에 **남긴 것을 먼저
말하는** 것이 이 문서의 용도다.

원칙 두 가지.
- **최소 수정.** 동결 중이라 프론트는 한 줄도 건드리지 않았다. 새 응답값은 화면이 무시하는
  `status` 로만 추가했고, 로그인만 429 를 쓰는데 화면이 `detail` 을 그대로 띄우므로 무수정.
- **전부 끌 수 있다.** 모든 차단은 설정값 `0` 으로 꺼진다. 시연 중 오작동하면 코드가 아니라
  값을 바꿔 되돌린다.

## 이미 돼 있던 것

점검 전에 이미 안전하게 만들어져 있던 항목. 보안은 못 한 것만 세기 쉬워서 같이 적는다.

| 항목 | 어디 | 어떻게 |
|---|---|---|
| 비밀번호 저장 | `app/auth.py` | PBKDF2-SHA256 20만 회, `compare_digest`. 없는 아이디도 해시를 한 번 돌려 응답 시간으로 계정 존재를 못 알아낸다 |
| 세션 | `app/auth.py` | HMAC 서명 쿠키. HttpOnly · Secure(운영) · SameSite=Lax. 서버에 세션 저장소가 없어 "캐시 장애 = 대량 로그아웃"이 성립하지 않는다 |
| 이미지 업로드 | `app/domain/image_security.py` | 본문을 스트리밍 중에 자르고, Pillow 로 열어 픽셀 수를 본 뒤 JPEG 로 **재인코딩**. 확장자·Content-Type 을 믿지 않으므로 폴리글롯·압축폭탄이 막히고 EXIF 도 지워진다 |
| 파일 경로 | `app/domain/storage.py` | 파일명은 난수, `is_relative_to` 로 경로 이탈 차단, 삭제는 우리가 만든 URL 만 |
| SQL | 전 라우터 | ORM 전용. 문자열 조립 없음 |
| XSS | `web/js/*` | 서버 데이터는 전부 `esc()` 를 거쳐 삽입. 외부 링크는 `rel=noopener` · `referrerpolicy=no-referrer` |
| 응답 헤더 | `app/main.py` | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` |
| CORS | `app/main.py` | GET 만, 출처는 명시 목록 |
| CSV 입력 | `app/domain/csv_import.py` | 5MB 스트리밍 컷, 필수 컬럼, `url` 스킴 검사, 행별 오류 보고 |
| 비밀값 | `.gitignore`, `config.py` | `.env*` 전부 제외(값이 빈 `.example` 만 커밋), 커밋 이력에 키·계정번호 없음 |
| 의존성 | `uv.lock` | 49개 패키지 pip-audit 알려진 취약점 0건 (2026-09) |

## 고친 것

| # | 문제 | 원인 | 조치 | 검증 |
|---|---|---|---|---|
| 1 | 로그인 무한 시도 | 실패를 세지 않았다 | 같은 IP 가 `LOGIN_MAX_FAILURES`(5)회 틀리면 `LOGIN_LOCKOUT_SECONDS`(300)초 429. 잠긴 동안은 비밀번호를 **검증조차 하지 않는다** — 하면 맞는 비밀번호에서 응답이 달라져 잠긴 채로 대입이 된다. **계정이 아니라 IP** 를 잠그는 이유: 계정을 잠그면 남이 `admin` 을 일부러 틀려 시연 중 관리자를 못 들어오게 할 수 있다 | `test_ratelimit.py` — 3번째 실패에서 즉시 429, 성공 시 리셋 |
| 2 | 실시간 검색 무한 호출 | 쿨다운이 "같은 검색어"만 봐서 검색어를 바꾸면 무제한으로 외부 사이트를 두드렸다 | IP 당 분당 `LIVE_SEARCH_RATE_LIMIT`(10)회. DB 를 보기 전에 `status="limited"` | `test_live_search.py` — 검색어 3개, 3번째 차단, 외부 호출 2번 |
| 3 | **크롤링 매물 가로채기** | CSV upsert 가 URL 기준이고 `source` 까지 덮어써서, 번개장터 URL 을 CSV 에 적으면 그 매물이 '직접등록'으로 바뀌고 사진까지 교체됐다. 사진 등록은 출처만 보고 판매자는 안 봤다 | 소유 규칙을 `app/domain/ownership.py::owns_item` 한 함수로: ① 직접등록이 아니면 누구 것도 아님 ② 매물 판매자 == 계정 판매자(한쪽이라도 None 이면 아님). CSV 는 저장 전에 남의 URL 행을 거절(`_reject_foreign_urls`), 사진 등록은 판매자까지 검사. 계정의 판매자 id 는 `User.seller_id` 가 들고 다닌다 — 지금은 `CLIENT_SELLER_ID` 에서 오지만 users 테이블이 생기면 `_seller_for()` 하나만 바뀌고 검사 코드는 그대로 | `test_ownership.py` — 가로채기 시도 후 원본 그대로, 다른 판매자 매물 403, 판매자 미지정 계정은 수정 불가 |
| 4 | 모든 프로세스가 마스터키 | `config.py` 가 임포트 시점에 관리자 비밀번호를 요구해서 크롤러도 받아야 떴다 | 요구를 그 값을 실제로 쓰는 `app/auth.py`(웹만 임포트) 의 `require_secrets()` 로 옮김. 크롤러·집계·백업은 `DATABASE_URL` 만으로 기동 | `test_secret_scope.py` — 서브프로세스로 "크롤러는 뜨고 웹은 죽는다" |
| 5 | DB 통신 평문 가능 | 연결 옵션이 없었다 | `DATABASE_SSL_MODE` (asyncpg sslmode). RDS 는 `require`, `verify-full` + `DATABASE_SSL_ROOT_CERT` 로 인증서·호스트명 검증까지. **기본은 `prefer`** — EC2 자체 Postgres 와 로컬 도커는 TLS 가 없어 `require` 면 기동이 안 된다. 운영에서 `prefer` 면 기동 로그에 경고 | `test_db_tls.py` |
| 6 | 클릭 부풀리기 | 세션·매물·30분 유니크는 있었으나 **쿠키를 안 보내면** 매 요청 새 세션이라 지나갔다 | IP 당 분당 클릭(`CLICK_RATE_LIMIT`) + **IP 당 시간당 새 쿠키 발급**(`CLICK_NEW_SESSION_LIMIT`). 정상 방문자는 쿠키 하나로 평생 쓰니 무관, 쿠키를 버리는 봇만 걸리고 걸리면 쿠키도 안 굽는다 | `test_clicks.py` — 쿠키 없이 3번째부터 차단, 쿠키 있으면 무관 |
| 7 | compose 가 환경변수를 안 넘김 | `--env-file` 은 `${...}` 치환용이라 `environment:` 에 없는 변수는 컨테이너에 안 들어갔다. `.env.web` 에 `APP_ENV=production` 을 적어도 컨테이너는 `local` 로 떠서 `admin1234` 로 로그인이 됐다 | `docker-compose.web.yml` 에 앱이 읽는 값을 전부 명시. 비밀번호는 `:?` 라 비면 `up` 단계에서 멈춤 | 기동 후 `admin1234` 로그인이 **401** 이어야 정상 |

호출 제한(1·2·6)은 `app/ratelimit.py` 의 슬라이딩 윈도우 하나를 공유한다. 표준 라이브러리만 쓰고
파드 안 메모리로 센다. 막힌 요청은 기록하지 않아 정당한 사용자가 돌아오면 풀린다.
`TRUST_PROXY_HEADERS`(운영 자동) 가 켜져야 ALB 뒤에서 `X-Forwarded-For` 로 사용자를 구분한다;
로컬에서는 꺼져 있어야 헤더 한 줄로 못 피한다.

## 남긴 것

알고 있으며, 시연 범위에서는 하지 않기로 한 것. 시간이 아니라 우선순위의 문제다.

- **호출 제한이 파드 단위.** 파드 3개면 상한이 3배로 느슨하다. 그래도 "무제한"과 "분당 30회"는
  다른 상태다. 파드를 가로지르는 상한은 WAF rate-based rule.
- **IP 를 바꿔가며 오는 봇넷.** 앱 단독으로는 막을 수 없다. WAF Bot Control, 또는 Phase 2 의
  큐+집계 단계에서 이상치 제거.
- **소유 검사의 SELECT↔upsert 틈.** 조회와 저장 사이에 크롤러가 같은 URL 을 넣는 경우. 닫으려면
  upsert 의 `ON CONFLICT ... WHERE` 절이 필요한데 크롤러 경로까지 건드린다.
- **CSP 헤더 없음.** `esc()` 가 1차 방어라 CSP 는 2차. 동결 중에 넣으면 인라인 스크립트가 깨질
  수 있다.
- **CSV 의 `image_url` 스킴 미검사.** `<img src>` 라 스크립트는 안 돌고 `no-referrer` 로 유출도
  막혀 트래킹 픽셀 정도.
- **DB 인증서 검증(`verify-full`)은 옵션.** RDS CA 번들을 마운트해야 해서 인프라 작업과 같이.
- **`/docs`·`/openapi.json` 은 앱에서 안 막는다.** 저장소가 공개라 API 목록은 어차피 보인다.
  실질 가치는 `/metrics`(실시간 트래픽·에러율) 차단이고 그건 ALB 고정 404 로.

## 인프라에 넘긴 것

앱 쪽은 값만 주면 되게 준비돼 있다. 순서가 있다.

1. RDS 파라미터 그룹 `rds.force_ssl=1` → ConfigMap / `.env.web` 에 `DATABASE_SSL_MODE=require`
2. gitops `secretScope.perWorkload: true` — **4번 패치가 머지된 이미지에서만.** 이전 이미지는
   크롤러가 관리자 비밀번호 없이는 안 뜬다
3. WAF: rate-based rule(로그인·검색·클릭의 파드 횡단 상한), ALB 리스너에서 `/metrics` `/docs`
   `/openapi.json` `/ready` 고정 404
4. S3 는 비공개 + CloudFront OAC, 예산 경보, 백업 복원 리허설

## 환경변수 요약

| 변수 | 기본 | 뜻 |
|---|---|---|
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_SECONDS` | `5` / `300` | IP 로그인 실패 잠금 |
| `LIVE_SEARCH_RATE_LIMIT` / `LIVE_SEARCH_RATE_WINDOW_SECONDS` | `10` / `60` | IP 실시간 검색 상한 |
| `CLICK_RATE_LIMIT` / `CLICK_RATE_WINDOW_SECONDS` | `60` / `60` | IP 클릭 상한 |
| `CLICK_NEW_SESSION_LIMIT` / `CLICK_NEW_SESSION_WINDOW_SECONDS` | `30` / `3600` | IP 새 클릭 세션 쿠키 발급 상한 |
| `TRUST_PROXY_HEADERS` | `APP_ENV` 따름 | `X-Forwarded-For` 신뢰 |
| `DATABASE_SSL_MODE` / `DATABASE_SSL_ROOT_CERT` | `prefer` / 비움 | DB 연결 암호화 |
| `CLIENT_SELLER_ID` | `0` | client 계정의 판매자. `0` 이면 수정 불가 |

전부 `0` 이면 그 제한은 꺼진다. 테스트(`conftest.py`)는 네 제한을 모두 끄고, 각 제한은
자기 테스트에서 리미터를 직접 주입해 검증한다.
