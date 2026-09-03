# 클릭 부풀리기 방어 — 적용 방법

CloudeDX 루트에 풀면 됩니다 (덮어쓰기). 기준: secretscope-tls 패치 적용 후
(`config.py`, `conftest.py`, `docs/deploy-env.md` 는 그 패치 위에 누적된 상태).

## 구멍
같은 세션·매물·30분 버킷은 DB 유니크가 한 번만 세지만, **쿠키를 안 보내면 매 요청
새 세션**이라 그 검사를 지나갔다. curl 로 쿠키 없이 1000번 → 1000 카운트 + 행 1000개.

## 막는 법 (`routers/events.py::record_click_event`)
- (a) `click_calls`: IP 당 분당 60회. 넘으면 202 + `status="limited"`, 세지 않음.
- (b) `new_sessions`: IP 당 시간당 새 쿠키 발급 30회. 쿠키 없이 왔는데 한도를 넘었으면
  **쿠키도 안 굽고 세지도 않음.** 정상 방문자는 쿠키를 평생 하나 받으니 영향 없음.
  쿠키를 들고 오는 요청은 이 한도와 무관 (테스트로 고정).
- 202 를 유지하는 이유: 이 엔드포인트 계약이 "화면은 결과와 무관하게 조용히 넘어간다".
  `sendBeacon` 은 응답을 읽지도 않는다.

## 파일
| 파일 | 무엇을 |
|---|---|
| `app/config.py` | `CLICK_RATE_LIMIT`(60) `CLICK_RATE_WINDOW_SECONDS`(60) `CLICK_NEW_SESSION_LIMIT`(30) `CLICK_NEW_SESSION_WINDOW_SECONDS`(3600) |
| `app/routers/events.py` | 두 리미터, `_valid_client_id()` 분리 |
| `app/schemas/events.py` | `status` 에 `limited` |
| `app/tests/conftest.py` | 테스트 환경에서 두 리미터 끔 |
| `app/tests/test_clicks.py` | 3개 추가 (쿠키 버리는 봇 / 쿠키 있는 방문자 무관 / IP 분당 상한) |
| `docs/deploy-env.md` | 환경변수 2줄 |

## 적용 후
`ruff check app && pytest -q` → 373 → 376.

## 여전히 남는 것
- 파드 단위 카운트 (WAF 가 파드 횡단 담당)
- IP 를 바꿔가며 오는 봇넷 — 이건 WAF Bot Control 이나 Phase 2 큐+집계에서 이상치 제거. 앱 단독으론 막을 수 없다.
