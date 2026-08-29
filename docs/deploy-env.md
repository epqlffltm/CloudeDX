# 운영 환경변수 계약 — 태스크 데피니션 작성용

> 대상 독자: 인프라 담당 팀원. 백엔드 컨테이너(3대)·크롤러 컨테이너(1대)·마이그레이션
> 일회성 태스크의 태스크 데피니션(ECS) 또는 매니페스트(EKS)에 넣을 환경변수 전부를
> 여기 모았다. **이 문서에 없는 변수는 넣지 않아도 된다** — 코드의 기본값으로 돈다.
>
> 근거 코드: `app/config.py` (모든 변수는 여기서 읽는다. 값 검증·기본값·기동 거부
> 로직 포함), `app/domain/storage.py` (S3 두 개만 예외적으로 자기 모듈에서 읽는다).

## 반드시 알아야 할 동작 하나

`APP_ENV=production` 이면 **비밀값 3개(SESSION_SECRET, ADMIN_PASSWORD,
CLIENT_PASSWORD)가 비어 있을 때 컨테이너가 기동을 거부한다** (임포트 단계에서
RuntimeError → CrashLoopBackOff). 버그가 아니라 설계다 — 기본 비밀번호로 뜬 서비스는
아무 증상 없이 위험하기 때문이다. 컨테이너가 계속 재시작하면 로그 첫 줄에 어떤
변수가 비었는지 나온다.

## 백엔드 컨테이너 (×3)

### 필수

| 변수 | 값 | 비고 |
|---|---|---|
| `APP_ENV` | `production` | 이 값이어야 위의 기동 거부·보안 기본값이 켜진다 |
| `DATABASE_URL` | `postgresql+asyncpg://유저:비번@주DB호스트:5432/cloudedx` | 쓰기 경로. **접두어가 `postgresql+asyncpg://`** 여야 한다 (`postgresql://`만 쓰면 안 뜸) |
| `SESSION_SECRET` | Secrets Manager에서 주입 | **3대가 반드시 같은 값**. 파드마다 다르면 "로그인이 됐다 안 됐다 하는" 버그가 된다 |
| `ADMIN_PASSWORD` | Secrets Manager에서 주입 | 관리자 계정 비밀번호 |
| `CLIENT_PASSWORD` | Secrets Manager에서 주입 | 기업고객 계정 비밀번호 |
| `ENABLE_CRAWLER` | `false` | 백엔드 이미지에는 Playwright가 없다. true면 크롤러 시작 시도 후 경고만 남기지만, 명시하는 것이 계약이다 |

### 강력 권장

| 변수 | 값 | 비고 |
|---|---|---|
| `DATABASE_RO_URL` | `postgresql+asyncpg://유저:비번@대기DB호스트:5432/cloudedx` | 읽기 복제본(대기 DB). 비우면 조회도 전부 주 DB로 간다 — 뜨긴 뜨지만 DB를 주+대기로 나눈 의미가 없다. 복제본 장애 시 런타임 폴백(서킷)과 기동 폴백이 모두 있으므로, 지정해서 잃는 것은 없다 |
| `S3_BUCKET` | 이미지 버킷 이름 | **컨테이너 배포에서는 사실상 필수.** 비우면 로컬 디스크 저장으로 떨어지는데, 3대 구성에서는 A서버에 올린 사진을 B서버가 못 주고 컨테이너 교체 시 사진이 사라진다 |
| `COOKIE_SECURE` | `true` | HTTPS(ALB에 인증서)면 true. `APP_ENV=production`이면 기본값이 이미 true라 생략 가능 — HTTP로만 시연한다면 그때만 명시적으로 `false` |

### 선택

| 변수 | 기본값 | 언제 바꾸나 |
|---|---|---|
| `S3_PUBLIC_BASE` | `https://{버킷}.s3.amazonaws.com` | CloudFront를 붙이면 그 도메인. 리전 리다이렉트를 피하려면 리전 포함 주소(`https://버킷.s3.ap-northeast-2.amazonaws.com`) 명시 권장 |
| `ALLOWED_ORIGINS` | (빈 값 = CORS 허용 없음) | 화면과 API가 같은 도메인(같은 ALB)이면 **필요 없다**. 도메인이 갈라질 때만 화면 도메인을 콤마 구분으로 |
| `LOG_LEVEL` | `INFO` | 장애 조사 때 `DEBUG` |
| `LOG_FORMAT` | `text` | CloudWatch 수집이면 `json` 권장 |
| `SESSION_MAX_AGE_SECONDS` | `43200` (12시간) | 시연 중 로그인 만료가 거슬리면 늘린다 |
| `WRITE_TIMEOUT_SECONDS` | `15` | 업로드·메모 저장의 DB 커밋 제한시간 |
| `MAX_UPLOAD_BYTES` | `5242880` (5MB) | 이미지 업로드 상한 |
| `READ_FALLBACK_COOLDOWN_SECONDS` | `30` | 복제본 장애 시 주 DB로 보내는 시간 |
| `ADMIN_USERNAME` / `CLIENT_USERNAME` | `admin` / `client` | 계정 아이디를 바꾸고 싶을 때만 |

지정하지 않는 변수: `UPLOAD_DIR` — S3 모드에서는 안 쓴다. `ADMIN_MEMO_PATH` —
**폐기됨** (메모가 DB 테이블 `admin_memo`로 옮겨져서 변수 자체가 사라졌다).

### IAM (환경변수가 아니라 역할)

S3 접근에 액세스 키를 환경변수로 넣지 않는다. 백엔드 태스크의 IAM 역할
(ECS: Task Role / EKS: IRSA)에 다음 권한을 부여한다:

- `s3:PutObject`, `s3:DeleteObject` — 대상: 이미지 버킷의 객체(`arn:aws:s3:::버킷/*`)

버킷 쪽 준비: 버킷 생성 + 이미지 객체 공개 읽기 정책(브라우저가 S3에서 직접
받는 구조다). 자세한 배경은 `app/domain/storage.py` 상단 설명 참고.

## 크롤러 컨테이너 (×1)

| 변수 | 값 | 비고 |
|---|---|---|
| `APP_ENV` | `production` | |
| `DATABASE_URL` | 백엔드와 동일 (주 DB) | 크롤러는 쓰기만 한다. RO_URL 불필요 |
| `ENABLE_CRAWLER` | `true` | |
| `CRAWL_INTERVAL_MINUTES` | 기본 `30` | 시연 리허설 때 수집 주기를 줄이고 싶으면 조정 |
| `LOG_LEVEL` / `LOG_FORMAT` | 백엔드와 동일 기준 | |

비밀값 3개(SESSION_SECRET 등)는 크롤러도 `app.config`를 임포트하므로 **같이
넣어야 기동한다** (production 가드가 동일하게 걸린다). 값은 백엔드와 같은 것을
재사용하면 된다.

S3 변수는 불필요 — 크롤링 이미지는 수집처 CDN URL을 그대로 참조하며 저장하지 않는다.

## 마이그레이션 일회성 태스크

배포마다 서비스 갱신 **전에** 한 번 실행: `alembic upgrade head`

| 변수 | 값 |
|---|---|
| `DATABASE_URL` | 백엔드와 동일 (주 DB — 복제본 아님!) |

앱 시작 시 자동 마이그레이션을 하지 않는 이유: 인스턴스 3개가 동시에 같은
마이그레이션을 돌리려 든다. 별도 태스크 1회가 정답이다 (compose의 migrate
서비스와 같은 역할).

## 로컬 검증용 compose와의 차이

`docker-compose.web.yml`의 `environment:` 블록에는 위 필수 변수 중
`APP_ENV`·`DATABASE_RO_URL`·`ADMIN_PASSWORD`·`CLIENT_PASSWORD`·`COOKIE_SECURE`가
빠져 있다 (로컬에서는 기본값으로 충분해서다). **compose 파일을 태스크 데피니션의
원본으로 복사하지 말 것** — 이 문서가 원본이다.

## 배포 전 점검 목록

- [ ] Secrets Manager에 SESSION_SECRET·ADMIN_PASSWORD·CLIENT_PASSWORD 등록, 3대가 같은 값 참조
- [ ] DATABASE_URL / DATABASE_RO_URL 접두어가 `postgresql+asyncpg://`
- [ ] 이미지 버킷 생성 + 공개 읽기 정책 + Task Role/IRSA에 PutObject·DeleteObject
- [ ] 배포 이미지에 boto3 포함 (`uv add boto3` — S3 모드 필수, 로컬 개발은 불필요)
- [ ] 마이그레이션 태스크를 서비스 갱신보다 먼저 실행하는 순서 확인
- [ ] ALB 헬스체크 경로: 로드밸런서 등록/제거 판단은 `/ready`, 컨테이너 생존 판단은 `/health`
      (둘의 차이는 `app/routers/health.py` 설명 참고 — /ready는 DB 상태까지 본다)
