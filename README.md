# CloudeDX — 중고 명품 통합검색 (브랜드명 Reverdi)

> CloudDX Academy 팀 프로젝트
> 담당: 백엔드 · 크롤러 · 프론트엔드 · 컨테이너 구성 (AWS 인프라는 별도 담당)
>
> **AWS 배포를 맡았다면 [배포와 인프라 인계](docs/deploy.md)부터 읽으면 된다.**
> 환경변수 계약은 [docs/deploy-env.md](docs/deploy-env.md)가 정본이다.

흩어져 있는 중고 거래처의 명품 매물을 한 곳에서 찾아보게 하는 서비스. 당근마켓 ·
중고나라 · 번개장터에서 매물을 주기적으로 수집해 PostgreSQL에 쌓고, 여기에 **입점
판매자(기업고객)가 직접 등록한 매물**을 더해, 브랜드 · 가격 · 판매처를 가로질러
비교할 수 있게 웹 화면과 REST API로 내보낸다.

거래처마다 검색 방식과 노출 정책이 달라 사용자가 세 사이트를 오가며 같은 조건을
다시 입력해야 하는데, 그 과정을 한 번으로 줄이는 것이 목적이다. 크롤링 대상은
여성용 명품 가방(구찌 · 에르메스 · 샤넬 · 루이비통)이고, 직접등록 경로는 시계 ·
주얼리 · 신발 · 의류까지 받는다 — 수집기와 스키마는 카테고리에 묶여 있지 않아
대상 확장은 브랜드 목록과 파서 추가로 처리된다.

파이프라인은 하나다:

```
크롤러(당근·중나 Playwright / 번장 API) ─┐
                                        ├→ items 테이블(upsert) → 서빙
기업고객 CSV·폼 등록 (/api/uploads)     ─┘        ├─ /      웹 화면 (web/, 정적 서빙)
                                                  └─ /api   JSON API
```

웹 화면은 `web/`의 정적 파일을 StaticFiles로 같은 출처에서 내보낸다 — 그래서 CORS
설정 없이 동작한다. 화면과 API는 같은 `app/db/repository.py`를 통해 조회한다 —
서로 다른 쿼리를 쓰기 시작하면 "API로는 나오는데 화면엔 없는" 상황이 생기기 때문이다.

매물을 모델 단위 "상품"으로 묶지 않고 **매물 그대로** 보여준다 — 경위는
[데이터베이스](docs/database.md)의 "가격 이력 — 도입했다가 제거함" 절에 있다.

## 현재 상태

| | |
|---|---|
| 실행 단위 | 백엔드 · 크롤러 두 이미지 |
| 구성 | 개발 단일 compose · 배포 계층별 compose(웹 / 크롤러 / 마이그레이션) |
| 스키마 | Alembic 마이그레이션 (판매자 · 매장 사진 · 관리자 메모 포함) |
| 화면 | 메인 · 로그인 · 관리자 콘솔 · 기업고객 포털 + 판매자 시트 (에디토리얼 리디자인) |
| 이미지 저장 | S3 이중 모드 — `S3_BUCKET` 설정 시 S3, 비우면 로컬 디스크 |
| 테스트 | 실제 Postgres 위에서 실행 (`uv run pytest`, 343건) + 프론트 스모크(`npm run test:web`) |
| CI | GitHub Actions — lint · test(파이썬 + 프론트 스모크) · 이미지 빌드 (AWS Secret 등록 시 ECR 푸시) |

## 빠른 시작

```
copy .env.example .env
docker compose up -d --build
```

화면 http://localhost:8000 · API 문서 http://localhost:8000/docs

시연 준비(판매자 시드 · CSV 업로드 · 매장 사진)는 [시연 가이드](docs/demo.md),
로컬에서 코드를 고치며 개발하는 방법은 [개발 가이드](docs/dev.md) 참고.

## 문서 목차

| 문서 | 내용 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 수집처별 역할 분담, 계층 분리, 프로세스 구성, 패키지 경계 |
| [docs/frontend.md](docs/frontend.md) | 웹 화면 4종, 헤더 드로어·마퀴·인기 탭, 판매자 시트(매장 사진·약도), 관리자 메모, 프론트-API 연결 |
| [docs/crawler.md](docs/crawler.md) | 등록 시각 환산, 수집 동작, 수집 예절·robots.txt, 브랜드 목록 |
| [docs/database.md](docs/database.md) | 마이그레이션, 매물 생명주기, 가격 이력을 제거한 경위, 클릭 집계, crawl_runs |
| [docs/api.md](docs/api.md) | API 계약, 클릭 집계·인기 매물, 매물 API와 도메인의 경계, /health·/ready, 로깅 |
| [docs/dev.md](docs/dev.md) | 로컬 실행, 환경 변수, 테스트, CI, 트러블슈팅, 알려진 이슈/TODO |
| [docs/deploy.md](docs/deploy.md) | 이미지 빌드, compose 구성, nginx를 제거한 경위, 인프라 인계 |
| [docs/deploy-env.md](docs/deploy-env.md) | **운영 환경변수 계약** — 태스크 데피니션 작성용 정본 |
| [docs/demo.md](docs/demo.md) | 시연 철학·순서, CSV 규칙, down -v 후 복구 |

## 스택

FastAPI · Playwright · PostgreSQL · SQLAlchemy(async) · Alembic · pytest · Docker · GitHub Actions · uv
