# 배포와 인프라 인계

> README에서 분리한 상세 문서다. 전체 지도는 [README](../README.md)의 문서 목차 참고.

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
| `backend` | API + 웹 화면 | `migrate` 성공 종료 |
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

### 배포 구성 — 계층별로 나눈 compose

서버 역할이 갈리므로 compose 도 셋으로 나눈다. `-f` 로 파일을 명시하지 않으면 도커가
`docker-compose.yml` 과 `docker-compose.override.yml` 을 자동으로 합치는데, override
에는 소스 마운트와 `--reload` 가 들어 있어 배포에 섞이면 안 된다.

| 파일 | 어디서 | 무엇이 |
|---|---|---|
| `docker-compose.web.yml` | 웹서버 3대(AZ당 1대) | 백엔드 1대 (ALB 직결) |
| `docker-compose.crawler.yml` | 크롤링 인스턴스 1대 | 크롤러만 |
| `docker-compose.migrate.yml` | 운영 서버 | 배포 스크립트가 1회 호출 |

DB 는 어느 파일에도 없다. 별도 인스턴스(주/대기 스트리밍 복제)에 있고 `DATABASE_URL`
로만 붙는다.

```
docker compose -f docker-compose.web.yml     --env-file .env.web     up -d
docker compose -f docker-compose.crawler.yml --env-file .env.crawler up -d
docker compose -f docker-compose.migrate.yml --env-file .env.migrate run --rm migrate
```

각 파일에 `name:` 을 못 박아 뒀다. 지정하지 않으면 compose 프로젝트명이 디렉토리명에서
자동으로 붙는데, 그러면 서버에서 디렉토리를 옮겼을 때 볼륨이 새로 만들어지면서 데이터가
사라진 것처럼 보인다.

#### 백엔드는 서버당 1대다

실제 배포는 3개 AZ 에 EC2 1대씩이고 분산은 ALB 가 한다. 서버 안에서 여러 대를
띄우면 t3.small(2GB) 에서 메모리가 빠듯하고, 분산 계층이 겹쳐 어느 쪽이 문제인지
가리기 어려워진다. 백엔드가 8000 을 직접 열고(웹 SG 인바운드 8000 = ALB SG 에서만),
ALB 가 그 포트로 직결한다.

#### 마이그레이션을 웹 compose 에서 뺀 이유

1. **동시 실행.** 웹서버 3대에 같은 compose 를 배포하면 세 대가 각자
   `alembic upgrade head` 를 돌린다. Alembic 이 락을 잡긴 하지만 경합이 생기고,
   밀린 쪽이 실패하면 그 서버만 뜨지 않는 애매한 상태가 된다.
2. **배포 순서.** 스키마 변경이 있는 배포는 "마이그레이션 → 앱 순차 교체" 순서여야
   한다. 웹 compose 안에 있으면 1번 서버가 새 코드로 뜨면서 마이그레이션이 함께 도는데,
   그 시점에 2·3번 서버는 아직 옛 코드로 새 스키마를 만난다.
3. **실패 처리.** 배포 스크립트에서 `run --rm` 으로 돌리면 종료 코드가 셸에 전달되어
   실패가 곧 배포 중단이 된다.
4. **ASG.** 웹서버는 자동 대체 기동 대상이다. 새 인스턴스가 뜰 때마다 마이그레이션이
   도는 것은 의도한 동작이 아니다.

#### DB 주소를 조립하지 않는다

로컬 구성은 `POSTGRES_*` 로 접속 문자열을 조립하지만, 배포에서는 `DATABASE_URL` 을
통째로 받는다.

```
DATABASE_URL=postgresql+asyncpg://cloudedx:<비밀번호>@db.reluxe.internal:5432/cloudedx
```

`db.reluxe.internal` 은 Route 53 프라이빗 호스팅 영역의 이름이다. 주 DB 장애로 대기
DB 를 승격하면 그 레코드만 바꾸면 되고, 웹서버 3대와 크롤러의 설정은 건드리지 않는다.
호스트가 바뀌는 게 아니라 "어디를 가리키는지"를 DNS 에 위임하는 것이다.

전환이 실제로 먹으려면 앱이 죽은 커넥션을 붙잡고 있으면 안 된다. `engine.py` 의
`pool_pre_ping=True` 가 체크아웃할 때마다 살아있는지 확인하고, 죽었으면 새로 맺으면서
그 시점에 DNS 를 다시 조회한다. **애플리케이션 코드 변경 없이 전환이 동작한다.**

#### 세션 키는 3대가 같아야 한다

ALB 스티키 세션을 쓰지 않는다. 로그인 상태가 서버에 저장되지 않고 HMAC 으로 서명한
쿠키에만 담기기 때문이다. 다만 그것은 **3대가 같은 키로 서명한다**는 전제 위에서만
성립한다.

`SESSION_SECRET` 이 비어 있으면 `config.py` 가 프로세스마다 임의 키를 만든다. 그러면
ALB 가 요청을 다른 서버로 보낼 때마다 쿠키 검증이 실패해 로그인이 붙었다 풀렸다 한다.
증상은 앱 버그처럼 보이지만 원인은 배포 설정이고, 3대로 흩어져 있으면 재현조차 어렵다.

그래서 배포 구성에서는 이 값에 기본값을 주지 않고 `:?` 로 **미설정 시 기동 자체를
거부**한다.

```
$ docker compose -f docker-compose.web.yml --env-file .env.web.example config
error while interpolating services.backend.environment.SESSION_SECRET:
  required variable SESSION_SECRET is missing a value:
  SESSION_SECRET 을 .env.web 에 설정하세요 — 3대 모두 같은 값
```

`:-` 로 기본값을 주면 `.env` 를 빠뜨렸을 때 개발용 값으로 조용히 떠버린다. 그런 실수는
뜨는 순간이 아니라 한참 뒤에 발견된다.

### nginx — 제거함

ALB 와 백엔드 사이에 nginx 를 한 겹 두는 구성을 만들었었지만, 배포를 ECS/EKS
컨테이너 오케스트레이션 + **ALB → 백엔드 직결**로 확정하면서 2026-08 에 걷어냈다.
분산은 어차피 ALB 가 하고 있었고, 중간 홉 하나는 설정·이미지·장애 지점 하나다.

nginx 가 하던 일의 행방:

- **보안 헤더·gzip**: `main.py` 미들웨어가 대체 — 응답 경로가 하나로 모이는 자리가
  프록시에서 앱으로 옮겨졌을 뿐, "한 곳에서 붙인다"는 원칙은 같다.
- **요청 단위 액세스 로그**: ALB 액세스 로그가 정본이 된다.
- **백엔드 재시작 시 대기**: ALB 헬스체크(`/ready`)가 죽은 대상을 뺐다가 복귀시킨다.
- **`/metrics` 외부 차단**: ALB 리스너 규칙에서 `/metrics` 를 고정 404 로 돌린다.
  수집기는 VPC 내부에서 8000 으로 직접 붙는다.

걷어낸 것: `nginx/` 디렉토리, CI 의 web 이미지 빌드·ECR 푸시,
`docker-compose.prod.yml`(한 호스트에서 nginx 분산으로 백엔드 3대를 검증하던
파일 — nginx 없이는 존재 이유가 없다), `.env.prod.example`.

요청마다 DNS 를 다시 묻는 변수 `proxy_pass`, 설정을 이미지에 굽는 이유 같은
nginx 시절의 설계 기록은 git 이력(2026-08 이전)에 있다.

### 프록시 뒤의 클라이언트 IP

`X-Forwarded-For` 는 누구나 붙일 수 있는 헤더다. 아무나 믿으면 클라이언트가 자기 IP 를
위조할 수 있어 접속 로그가 오염되고 IP 기반 제한도 무의미해진다.

배포에서는 체인이 한 단계다 (nginx 를 걷어내면서 한 홉 줄었다):

```
클라이언트 → ALB → uvicorn
```

ALB 가 `X-Forwarded-For` 에 클라이언트 IP 를 넣어 주므로, uvicorn 은 ALB 의 사설
IP(VPC 대역)가 보낸 헤더만 신뢰하면 된다.

```
FORWARDED_ALLOW_IPS=10.0.0.0/16
```

`Dockerfile` 의 `CMD` 는 셸 형식으로 써서 `FORWARDED_ALLOW_IPS` 를 읽는다. exec
형식(JSON 배열)에서는 `$VAR` 가 치환되지 않고 문자 그대로 전달된다. 기본값은 로컬 개발
편의를 위해 `*` 로 두고, 배포에서 compose 가 덮어쓴다.


## 인프라 인계

AWS 배포(EC2 프로비저닝 · 네트워크 · 보안그룹 · 부하 테스트)를 맡은 담당자를 위한 절이다.
이 저장소는 **"이미지와 compose 파일만 있으면 뜨는 상태"**까지를 넘긴다.

### 서버 역할과 파일

| 서버 | compose | env | 대수 |
|---|---|---|---|
| 웹서버 | `docker-compose.web.yml` | `.env.web` | 3 (AZ당 1) |
| 크롤링 | `docker-compose.crawler.yml` | `.env.crawler` | 1 |
| 운영 | `docker-compose.migrate.yml` | `.env.migrate` | 배포 시 1회 |
| DB | (없음) | — | 주 1 · 대기 1 |

DB 는 이 저장소가 다루지 않는다. 앱은 `DATABASE_URL` 로만 붙는다.

`.env.*`(실제 값이 든 파일)는 저장소에 없다. `.gitignore` 에 막혀 있고 서버에서 직접
만든다. 템플릿(`.env.*.example`)만 커밋돼 있다.

### 인스턴스 요구사항

**웹서버 — t3.small(2GB) 이상**

| 구성요소 | 대략 |
|---|---|
| 백엔드 1대 | ~150MB |

**크롤링 — t3.medium(4GB)**

크롤러가 Chromium 을 띄우면서 `shm_size: 1gb` 를 잡는다. 컨테이너 기본 `/dev/shm` 이
64MB 뿐이라 그대로 두면 페이지를 열다 죽는다. `--disable-dev-shm-usage` 로 우회할 수도
있지만 디스크를 대신 쓰게 되어 느려진다.

디스크는 이미지 두 개(백엔드 564MB + 크롤러 3.59GB)만으로 4GB 를 넘으므로
**20GB 이상**을 잡는다. 컨테이너 로그는 compose 에 로테이션(`max-size: 10m`,
`max-file: 3`)이 걸려 있어 쌓이지 않는다.

### 보안그룹

설계도의 SG 구성과 이 저장소의 compose 는 이렇게 맞물린다.

| SG | 인바운드 | compose 쪽 대응 |
|---|---|---|
| 웹 | 8000 (ALB SG 에서만) | 백엔드가 `ports: 8000:8000` |
| 크롤링 | 없음 | 크롤러는 HTTP 를 열지 않는다 |
| DB | 5432 (웹·배치·DB SG) | 앱이 `DATABASE_URL` 로 나간다 |

백엔드가 8000 을 직접 연다(nginx 를 걷어내면서 바뀐 점). 그 포트로 들어올 수 있는
것은 보안그룹 규칙상 ALB 뿐이고, `/metrics` 는 ALB 리스너 규칙에서 고정 404 로 돌려
외부 노출을 막는다.

SSH 22 는 열지 않는다(SSM Session Manager). 컨테이너는 non-root(uid 10001)로 실행되며
Dockerfile 에 이미 적용돼 있다.

### 이미지 전달

CI 가 main 푸시마다 ECR 로 올린다. 태그는 커밋 해시 7자리와 `main` 두 가지다.

```bash
# 서버에서
docker compose -f docker-compose.web.yml --env-file .env.web pull
docker compose -f docker-compose.web.yml --env-file .env.web up -d
```

`.env.web` 의 이미지 변수를 해시 태그로 고정하면 어느 커밋이 떠 있는지 알 수 있고,
롤백은 태그를 옛 해시로 바꾸고 다시 `pull` 하면 끝난다.

```
WEB_IMAGE=<계정>.dkr.ecr.ap-northeast-2.amazonaws.com/reluxe-web:a1b2c3d
BACKEND_IMAGE=<계정>.dkr.ecr.ap-northeast-2.amazonaws.com/reluxe-backend:a1b2c3d
```

CI 가 아직 연결되지 않았다면(아래 "필요한 AWS 설정" 참고) 수동으로 옮긴다:

```bash
docker save reluxe-backend:latest reluxe-web:latest | gzip > images.tar.gz
scp images.tar.gz <서버>:~/          # SSM 을 쓴다면 포트 포워딩 경유
gunzip -c images.tar.gz | docker load
```

크롤러 이미지가 3.59GB(압축 후 ~1.2GB)라 시간이 걸린다.

### 필요한 AWS 설정

CI 가 ECR 로 올리려면 이것들이 있어야 한다.

1. **ECR 리포지토리 3개** — `reluxe-web` · `reluxe-backend` · `reluxe-crawler`
   (수명주기 정책 최근 10개 유지)
2. **GitHub OIDC 자격증명 공급자** — `token.actions.githubusercontent.com`
3. **IAM 역할** — 위 공급자를 신뢰하고 조건에
   `repo:epqlffltm/CloudeDX:ref:refs/heads/main` 제한. 권한은 ECR push
4. 역할 ARN 을 저장소 Settings → Secrets 에 **`AWS_ROLE_ARN`** 으로 등록

4번이 없으면 CI 의 `build` 잡이 ECR 인증 단계에서 실패한다. `lint` 와 `test` 는
그대로 통과한다.

### 서버에서 할 일

**웹서버 3대 (각각 동일)**

```bash
cp .env.web.example .env.web
# DATABASE_URL, SESSION_SECRET, 이미지 주소를 채운다
docker compose -f docker-compose.web.yml --env-file .env.web up -d
```

`SESSION_SECRET` 은 **3대가 같은 값**이어야 한다. 하나만 다르면 그 서버로 간 요청에서만
로그인이 풀려, 재현이 안 되는 버그처럼 보인다. 생성:

```bash
openssl rand -hex 32
```

**크롤링 인스턴스**

```bash
cp .env.crawler.example .env.crawler
docker compose -f docker-compose.crawler.yml --env-file .env.crawler up -d
```

**운영 서버 (배포 스크립트)**

```bash
# 1. 스키마를 먼저 올린다. 실패하면 여기서 멈춘다.
docker compose -f docker-compose.migrate.yml --env-file .env.migrate run --rm migrate

# 2. 웹서버를 한 대씩 교체한다.
#    ALB 등록 취소 지연 30초를 감안해 대기를 둔다.
```

### 기동 확인

각 웹서버에서:

```bash
curl http://localhost:8000/health      # 200   — 프로세스 생존
curl http://localhost:8000/ready       # 200   — DB·스키마까지
```

`ps` 의 기대 상태:

| 컨테이너 | 상태 | 포트 |
|---|---|---|
| `backend` | Up (healthy) | `0.0.0.0:8000->8000/tcp` |

8000 이 호스트에 열리는 것이 맞다(nginx 를 걷어내면서 바뀐 점) — ALB 가 이 포트로
직결하며, 외부 접근은 보안그룹(ALB SG 에서만)이 막는다.

ALB 헬스체크 대상은 `/ready` 로 잡는다(설계도대로 10초 간격, 2회 실패 시 제외).
`/health` 가 아닌 이유는 [API 문서](api.md)의 "상태 확인" 절에 있다 — 요약하면 `/health` 는 프로세스가
살아있는지만 보고 DB 가 죽어도 200 을 준다. 그것을 헬스체크로 쓰면 DB 장애 시 모든
인스턴스가 정상으로 보이면서 오류만 뱉는다.

파이프라인이 도는지:

```bash
curl http://localhost/api/meta         # last_crawled_at 이 갱신되는가
```

### 흔히 걸리는 것

**`InvalidPasswordError: password authentication failed`**
DB 비밀번호를 바꿨는데 데이터 볼륨이 남아 있는 경우다. `POSTGRES_*` 는 볼륨이 비어
있을 때만 반영되므로 DB 에는 옛 비밀번호가 그대로다.

**`required variable ... is missing a value`**
`.env` 에 시크릿이 비어 있다. 의도된 동작이다 — 설정 누락 상태로 뜨지 않는다.
`--env-file` 경로가 맞는지도 확인한다.

**로그인이 새로고침할 때마다 풀린다**
웹서버 3대의 `SESSION_SECRET` 이 서로 다르다. 세 대에서 값을 비교한다:

```bash
docker compose -f docker-compose.web.yml --env-file .env.web exec backend \
  printenv SESSION_SECRET
```

**크롤러가 재시작을 반복한다**
DB 에 못 붙는 경우가 대부분이다. 같은 compose 안에 있을 때는 `depends_on` 으로 순서가
보장됐지만 인스턴스가 갈리면서 그 보장이 사라졌다. `restart: unless-stopped` 가 DB 가
준비될 때까지 다시 띄우므로 결국 붙는다. 몇 분 넘게 반복하면 보안그룹이나 Route 53
레코드를 확인한다.

**화면은 뜨는데 데이터가 안 늘어난다**
크롤링 인스턴스가 멈춘 것이다. 사용자 화면은 DB 에 있던 데이터를 계속 서빙하므로 며칠
지나서야 발견된다. `/api/meta` 의 마지막 수집 시각으로 감시하고, 2시간 이상 갱신되지
않으면 경보를 낸다.

### 운영

```bash
# 로그 (요청 단위 기록은 ALB 액세스 로그가 정본이다 — uvicorn 액세스 로그는 꺼져 있다)
docker compose -f docker-compose.web.yml --env-file .env.web logs -f backend
docker compose -f docker-compose.crawler.yml --env-file .env.crawler logs -f crawler

# DB 접속 (호스트 포트가 없으므로 DB 인스턴스에서 컨테이너 안으로)
docker compose exec db psql -U cloudedx -d cloudedx
```

### 앱이 내보내는 지표

설계도의 "앱 지표(직접 발행)"에 해당하는 것은 `/api/meta` 다.

| 항목 | 쓰임 |
|---|---|
| 마지막 수집 시각 | 2시간 이상 갱신 없으면 "주의" |
| 수집 상태(`crawl_runs`) | 실행 중 · 성공 · 실패 · 중단 판정 |
| 파싱 실패율 | 사이트 구조 변경 감지 |

`/ready` 는 DB 접속과 Alembic 리비전 일치를 함께 확인하므로, 이것이 200 이면
"이 인스턴스는 지금 요청을 받아도 된다"는 뜻이다.

### TLS

TLS 는 **ALB 에서 종단**한다 (nginx 를 걷어내면서 다른 선택지가 없어졌고, 애초에
권장이던 방식이다). ACM 인증서를 ALB 리스너(443)에 붙이면 백엔드 쪽은 건드릴 것이
없다 — uvicorn 은 `--proxy-headers` 로 `X-Forwarded-Proto` 를 읽으므로,
`FORWARDED_ALLOW_IPS` 가 VPC 대역으로 잡혀 있으면 쿠키 `Secure` 판정도 맞게 동작한다.

### 확인이 필요한 값

| 항목 | 지금 | 확정 필요 |
|---|---|---|
| VPC 대역 | `10.0.0.0/16` (설계도 예시) | 실제 값 |
| Route 53 이름 | `db.reluxe.internal` | 실제 값 |
| ECR 계정 ID | — | 이미지 주소에 들어감 |
