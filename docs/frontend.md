# 웹 화면

> README에서 분리한 상세 문서다. 전체 지도는 [README](../README.md)의 문서 목차 참고.

## 화면

화면은 `web/`의 정적 웹 화면 하나다. 예전에 있던 Jinja2 게시판(/board)은
제거했다 — 경위는 이 절 끝의 "게시판 — 제거함" 참고.

### 웹 화면 (web/) — 에디토리얼 리디자인

2026-08에 전 화면을 리디자인했다. 흰 바탕 + 먹색 모노크롬, 세리프 워드마크
(REVERDI), 넓은 자간의 대문자 라벨 — 디자인 도구(Stitch) 시안의 디자인 언어만
가져오고, 시안이 준 코드(Tailwind CDN · 별도 서버 · 목데이터)는 쓰지 않았다.
기존 구조(html / css / js 분리, 모듈 JS, 이벤트 위임) 위에 다시 썼고,
`home.js` `api.js` `state.js` `auth.js`와 백엔드는 수정하지 않았다.

| 화면 | 파일 | 구성 |
|---|---|---|
| 메인 | `index.html` + `css/reverdi.css` | 히어로 · 카테고리 · 브랜드 스포트라이트 · 검색 결과 |
| 로그인 | `login.html` + `css/login.css` + `js/login.js` | 카드형 폼 · 비밀번호 표시 토글 · 시연 계정 블록 |
| 관리자 콘솔 | `admin.html` + `css/admin.css` + `js/admin.js` | 해시 라우팅 6화면 (대시보드 · API · DB · 크롤러 · 분포 · 메모) |
| 기업고객 포털 | `client.html` + `css/client.css` + `js/client*.js` | 해시 라우팅 3화면 (내 매물 · 단건 등록 · CSV 일괄 등록) |

리디자인에서 지킨 원칙 둘:

**구조는 유지한다.** 각 페이지의 JS가 참조하는 id · 클래스 · data-속성이 곧 계약이다.
HTML/CSS를 갈아엎어도 그 계약(`.p-card`, `data-brand`, `data-view` 등)을 유지하면
JS와 백엔드를 건드릴 필요가 없다. 실제로 메인 화면은 JS 무수정으로 끝났다 —
새로 넣은 브랜드 스포트라이트 버튼도 `data-brand="에르메스"`만 달면 기존 이벤트
위임이 필터 화면으로 보낸다.

**화면은 거짓말하지 않는다.** 뒷받침할 API나 데이터가 없는 요소는 그리지 않는다.
시안의 "100% Verified" 배너(크롤링 매물은 검증 대상이 아님), Remember me(세션
시간은 서버 고정), 30일 가동률(집계 저장소 없음), Settings 메뉴(설정이 환경변수라
저장할 API 없음)는 전부 뺐거나 실존 데이터로 대체했다. 메뉴는 "누르면 동작하는
것이 있다"는 약속이고, 지킬 수 없는 약속은 걸지 않는다.

화면별 눈여겨볼 결정:

- **관리자 콘솔**: 사이드바 항목마다 화면이 전환된다(해시 라우팅 — 별도 페이지로
  쪼개면 같은 데이터 로드가 다섯 벌이 된다). 모든 숫자가 실데이터다: 서버 카드는
  `/health` + 브라우저 측정 응답시간, DB 카드는 `/ready`(읽기/쓰기/마이그레이션),
  API 모니터링은 **`/metrics`(Prometheus 텍스트)를 admin.js가 직접 파싱**한다 —
  가동 시간은 `process_start_time_seconds`, 표는 핸들러별 누적 요청·오류·평균 지연.
  트래픽 스파크라인은 화면을 열어 둔 동안 10초 폴링의 증가분 실측이라 새로고침하면
  초기화된다(서버에 시계열 저장소가 없으므로 그게 정직한 동작이다).
- **기업고객 단건 등록**: 전용 API를 만들지 않았다. 폼 입력을 **1행짜리 CSV로
  조립해 기존 `/api/uploads/csv`로** 보낸다 — 저장 경로가 하나여야 제목 정제 ·
  브랜드 판정 · url 중복 규칙이 일괄 등록과 완전히 같아진다. 정품인증 토글은 CSV
  스키마에 실존하는 `is_authenticated` 컬럼이다.
- **client.js ↔ client_photos.js**: 서로의 함수를 부르지 않는다. 등록/업로드가
  성공하면 `reverdi:items-changed` 커스텀 이벤트만 쏘고, 목록 쪽은 그 이벤트를
  듣고 다시 불러온다.
- 한글 최소 글자 크기 12.5px(시안의 9~10px 한글은 가독성 문제로 키움), 아이콘은
  인라인 SVG(아이콘 폰트 미사용 — 요청이 줄고 폐쇄망에서도 뜬다), CSS는 페이지당
  한 파일(공유 CSS는 한 화면을 고칠 때 다른 화면이 같이 변하는 사고가 난다).

정리: 어느 페이지도 참조하지 않게 된 `css/tokens.css`·`css/account.css`는 삭제했고,
예전 admin.html이 참조하던 존재하지 않는 `css/app.css` 링크(매 로드 404)도 교체로
사라졌다. 네 HTML 전부에 파비콘(`web/favicon.svg`, 먹색 R 모노그램)이 달려 있다.
메인 헤더의 LOGIN 버튼은 로그인 상태를 확인해(fetchMe) 로그인돼 있으면 역할에 따라
Console(admin.html) 또는 My Page(client.html) 링크로 바뀐다.

### 헤더·드로어·마퀴 (2026-08-31)

카테고리 줄을 헤더에서 빼고 왼쪽 **사이드 드로어**(햄버거 버튼)로 옮겼다. 대문은
브랜드 사이트처럼 조용하게 두고, 카테고리는 검색 결과 화면의 **카테고리 칩 줄**
(`#categoryChips`)에서 바로 고른다 — 필터 앞에서 햄버거를 열게 하면 마찰이다.
드로어의 `#mainNav`는 예전과 같이 `renderNav()`가 /api/meta로 채운다. 배경·닫기·
Esc·카테고리 선택으로 닫히고, 열릴 때 닫기 버튼으로 포커스가 간다. 드로어에
기업고객 링크는 두지 않는다 — 헤더 Login과 대문 For Business 블록으로 충분하다.

Maisons 브랜드 줄은 **마퀴**다. `#brandScroll`(원본 한 벌) 뒤에 home.js
`layoutBrandMarquee()`가 화면 폭에 맞춰 복제본을 붙이고 한 벌 폭만큼만 이동시켜
끊김 없이 돈다(초당 약 22px, 왼쪽 흐름 — 읽는 방향). 마우스를 올리면 멈추고,
`prefers-reduced-motion`이면 정지한 채 가로 스크롤로 남는다. 검색 모드에서 대문이
숨겨져 폭이 0이 되므로 `goHome()`에서 다시 잰다. 방향을 바꾸려면
`@keyframes brand-marquee`의 from/to만 바꾼다.

대문 레일에 **인기 물품** 탭이 추가됐다(신규·인증 옆 세 번째) — `/api/products/popular`. 카드마다
`data-item`이 붙고, 카드 클릭은 이벤트 위임에서 `sendClick()`으로 서버에 알린 뒤
본래 동작(원문 링크·판매자 시트)을 그대로 이어간다([API](api.md) "클릭 집계").

### 판매자 시트 — 입점 판매자

매물 카드에 `seller_id`가 있으면(직접등록 매물) 카드를 눌렀을 때 원문 링크 대신
**판매자 시트**(모달)가 열린다. Stitch 목업을 재현한 화면으로, 상호·소개·사업자
등록번호·연락처·주소·매장 사진·대표 제품·찾아오시는 길·연락하기 CTA로 구성된다.
하드코딩은 없다 — 전부 `/api/sellers/{id}`와 목록 API에서 온다.

- **판매자 데이터**: `sellers` 테이블. 계정 테이블이 아니라 화면에 보여줄 사업자
  정보다(로그인 계정은 설정 기반 2개뿐). 시연 시드(`app/seed_demo.py`)가 8명을
  깐다 — 매장 보유 5, 온라인 전용 3. 온라인 전용은 주소·좌표·사진이 없는 것이
  정상이고 화면은 그 칸을 그리지 않는다.
- **매장 사진** (`sellers.photo_url`): 간판·가게 내부 사진. 매물 사진과 별개 컬럼이다 —
  가게 소개 칸에 파는 물건 사진이 대신 걸리면 안 되기 때문. 시드는
  `web/img/sellers/{slug}.jpg` 정적 파일을 가리키므로, **같은 파일명으로 실사
  이미지를 덮어쓰면 코드·DB 수정 없이 반영된다.**
- **약도** (`home.js`의 `sketchMap`): 외부 지도 API 없이 브라우저가 그리는 SVG다.
  판매자 id를 시드로 한 결정적 난수라 같은 판매자는 늘 같은 약도가 나온다.
  큰길 교차·지하철역·공원·은행 같은 읽을 수 있는 표지를 고정 문법으로 깔고 난수는
  위치만 흔든다. 지명은 전부 가상 — 실지명을 쓰면 진짜 지도로 오해된다. 정확한
  위치가 필요한 사람은 View Directions로 카카오맵(공개 링크 스킴)에 간다.
- **업로드 매물 ↔ 판매자 연결** (`CLIENT_SELLER_ID`): 계정↔판매자 정식 연결이 없는
  자리의 임시 다리다. 0(기본)이면 연결 안 함, 지정하면 client 계정이 올린 매물이
  그 판매자에 연결돼 시트가 열린다. 없는 id면 경고만 남기고 업로드는 성공한다 —
  설정 실수 하나가 시연 전체를 막으면 안 되기 때문. 시연 값은 1(청담 명품관).

### 관리자 메모 — 게시판을 걷어낸 자리

관리자 콘솔(admin.html)의 "메모" 화면은 관리자들이 공용으로 쓰는 텍스트 한 장이다.
인수인계·작업 기록 용도다(/api/admin/memo, app/routers/memo.py).
처음에는 요구('txt 파일처럼') 그대로 서버 파일 하나였는데, 배포가 백엔드 여러 대 + 컨테이너로 확정되면서 DB의 한 줄짜리 테이블(admin_memo, 항상 id=1)로 옮겼다 
— A 서버에 저장한 메모를 B 서버가 모르고, 컨테이너 교체와 함께 파일이 사라지기 때문이다.
상한 64KB·관리자 전용·전체 덮어쓰기(PUT)라는 계약은 그대로라 화면 코드는 이 이전을 모른다.

### 게시판 — 제거함

`/board`(Jinja2 게시판)는 2026-08에 제거했다. 웹 화면(web/)이 목록·필터·상세를 전부
갖추면서 역할이 겹쳤고, 화면 두 벌을 유지하면 손보는 쪽과 잊히는 쪽이 갈라진다.

게시판에만 있던 것들의 행방:
- **등록 후 경과 막대** (오래 걸린 매물 = 협상 여지 찾기): 웹 화면에 아직 없다.
  필요해지면 `posted_at`이 이미 API로 내려오므로 프론트에서만 붙일 수 있다.
- JS 없는 GET form 필터 (공유 가능한 링크): 웹 화면도 필터 상태를 주소창에
  기록하므로(`writeURL`) 링크 공유는 동일하게 된다.
- 걷어낸 것: `app/routers/web.py`, `app/templates/`, 게시판 렌더링 테스트.
  이 제거로 백엔드에서 Jinja2 의존이 사라졌다.


### 프론트엔드 연결

API는 `/api` 아래에 모여 있다. 화면 경로와 분리해 뒀기 때문에, 리버스
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

#### 응답 예시

`GET /api/crawled-items?brand=샤넬&limit=20`

```json
{
  "total": 655,
  "count": 20,
  "limit": 20,
  "offset": 0,
  "has_next": true,
  "items": [
    {
      "id": 1,
      "source": "당근마켓",
      "brand": "샤넬",
      "category": "bag",
      "title": "샤넬 클래식 플랩 미디움 캐비어",
      "price": "4,000,000원",
      "price_value": 4000000,
      "region": "서초구 반포동",
      "time_text": "3시간 전",
      "posted_at": "2026-08-12T05:10:00Z",
      "image_url": "https://img.kr.gcp-karroter.net/origin/article/...",
      "url": "https://www.daangn.com/kr/buy-sell/...",
      "is_sold": false,
      "is_active": true,
      "unavailable_at": null,
      "unavailable_reason": null,
      "first_seen_at": "2026-08-10T02:00:00Z",
      "last_seen_at": "2026-08-12T08:30:00Z"
    }
  ]
}
```

프론트에서 주의할 필드가 셋 있다.

- **`price` vs `price_value`** — 앞은 사이트 원문(`"400만원"`처럼 제각각), 뒤는 파싱한
  숫자다. 정렬이나 비교에는 `price_value`를 쓰고, 파싱에 실패하면 `null`이라
  "가격 미상"으로 표시해야 한다. 가격 필터를 걸면 이런 매물은 결과에서 빠진다.
- **`posted_at`이 `null`일 수 있다** — 사이트가 등록 시각을 표기하지 않은 경우다.
  이때는 `first_seen_at`으로 대체하되 "등록"이 아니라 "수집"이라고 적어야 한다.
  수집 시각을 등록일처럼 보여주면 실제보다 최근 글로 오해한다.
- **`is_active`** — 기본 응답에는 활성 매물만 담긴다. 판매완료·미발견 매물까지 보려면
  `include_inactive=true`를 붙여라. `unavailable_reason`이 `sold`면 사이트가 표기한
  사실, `missing`이면 연속 미발견에 따른 추정이라 신뢰도가 다르다.

`GET /api/products?brand=샤넬&limit=20` — 목록 껍데기(total/count/limit/offset/has_next)는
같고 `items` 원소만 다르다:

```json
{
  "id": 1,
  "source": "당근마켓",
  "title": "샤넬 클래식 플랩 미디움 캐비어",
  "brand": "샤넬",
  "category": "bag",
  "price": 4000000,
  "image_url": "https://img.kr.gcp-karroter.net/origin/article/...",
  "item_url": "https://www.daangn.com/kr/buy-sell/..."
}
```

`GET /api/meta`

```json
{
  "sources": ["당근마켓", "중고나라"],
  "brands": ["구찌", "에르메스", "샤넬", "루이비통"],
  "total_items": 655,
  "last_crawled_at": "2026-08-12T08:30:00Z",
  "crawler": {
    "is_running": false,
    "stale": false,
    "started_at": "2026-08-12T08:25:00Z",
    "last_finished_at": "2026-08-12T08:30:00Z",
    "last_item_count": 655,
    "last_error": null,
    "rounds_completed": 12,
    "interval_minutes": 30
  }
}
```

`crawler`를 내려주는 이유는 **방금 뜬 서버는 목록이 비어 있기 때문이다.** 그게
"매물이 없다"인지 "아직 수집 중"인지 프론트가 구분할 수 있어야 한다.

- `is_running: true` → "수집 중" 배너를 띄우고 잠시 후 목록을 다시 부른다
- `rounds_completed: 0` → 아직 한 번도 성공하지 못한 상태
- `last_error`에 값이 있어도 수집이 멈춘 건 아니다. 일부 사이트만 실패한 경우에도
  기록되므로, 경고로 표시하되 오류 화면으로 덮지는 말 것
- `stale: true` → 크롤러가 비정상 종료된 흔적. 운영자가 봐야 할 신호다

**타입 생성**: 각 엔드포인트에 `operation_id`를 명시해 뒀다(`listCrawledItems`, `getCrawledItem`,
`getMeta`, `listListings`, `getListing`). `/openapi.json`에서 스키마를 받아
클라이언트를 생성하면 이 이름이 함수명이 된다. 지정하지 않으면 경로를 바꿀 때마다
프론트의 함수 이름까지 따라 바뀐다.

**에러 형태**: 404 등은 FastAPI 기본인 `{"detail": "..."}`, 검증 실패(422)는
`{"detail": [{...}]}` 배열이다. 프론트에서 `detail`이 문자열인지 배열인지 구분해서
처리해야 한다.
