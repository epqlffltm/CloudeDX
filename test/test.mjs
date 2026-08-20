// fetest/test.mjs
// 브라우저 없이 화면 전체를 검증한다: index.html을 jsdom에 올리고,
// 배포본 main.js를 그대로 import해서 진짜 백엔드(5000)에 붙인 뒤
// 사용자 흐름을 대문부터 순서대로 돈다:
//   대문(스크롤 로딩) → 대문 검색 전환 → 가방 카테고리 → 필터 →
//   페이지네이션 → 검색 제목 → 정렬 → 슬라이더 → 카테고리 전환.
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const dom = new JSDOM(html, { url: "http://localhost:5000/" });

// API_BASE가 상대 경로("")가 되면서 앱은 fetch("/api/...")를 부른다. 브라우저는
// 문서 주소를 기준으로 풀지만 node의 fetch는 기준이 없어 절대 주소를 요구한다
// — 테스트에서만 기준을 접붙인다. 앱 코드는 손대지 않는다.
const realFetch = globalThis.fetch;
globalThis.fetch = (url, opts) => realFetch(new URL(url, "http://localhost:5000/"), opts);

// main.js는 모듈 평가 시점에 document·history·location을 만진다 —
// import 전에 jsdom 전역을 노드 전역으로 승격시킨다.
globalThis.document = dom.window.document;
globalThis.history = dom.window.history;
globalThis.location = dom.window.location;

// jsdom에는 IntersectionObserver가 없다. observe 즉시 "보인다"고 답하는
// 가짜를 심는다 — 대문의 스크롤 로딩 배선(장전→로드→재장전 체인)이
// 실제로 이어지는지를 검증하는 게 목적이다.
globalThis.IntersectionObserver = class {
  constructor(cb) {
    this.cb = cb;
  }
  observe(el) {
    queueMicrotask(() => this.cb([{ isIntersecting: true, target: el }], this));
  }
  unobserve() {}
  disconnect() {}
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(pred, ms = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (pred()) return true;
    await sleep(60);
  }
  return false;
}

const $ = (s) => dom.window.document.querySelector(s);
const $$ = (s) => [...dom.window.document.querySelectorAll(s)];
const click = (elm) =>
  elm.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
const submitSearch = () =>
  $("#searchForm").dispatchEvent(
    new dom.window.Event("submit", { bubbles: true, cancelable: true }),
  );
const body = dom.window.document.body;

let pass = 0;
let fail = 0;
const ok = (name, cond) => {
  cond ? pass++ : fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}`);
};

// --- 0) escapeHtml 단위 확인 -------------------------------------------------
const { escapeHtml } = await import("../js/render.js");
ok(
  "escapeHtml이 5종 특수문자를 전부 바꾼다",
  escapeHtml(`<b a="1">&'`) === "&lt;b a=&quot;1&quot;&gt;&amp;&#39;",
);

// --- 1) 대문 (/, 파라미터 없음) ----------------------------------------------
await import("../js/main.js");

ok("대문 모드 클래스", body.classList.contains("mode-home"));
ok("대문 제목 '전체'", $("#listTitle").textContent === "전체");
ok("본문 카드 중 활성 없음 (전체엔 카드가 없다)", $$(".cat.cat--active").length === 0);
ok("헤더 내비의 '전체'가 활성", $$(".tnav__item.cat--active").length === 1
  && $(".tnav__item.cat--active").dataset.category === "all");

// 가짜 옵저버가 즉시 발화 → 첫 페이지 → 재장전 → 끝까지 자동 체인
await until(() => $$("#grid .card").length === 44);
ok("스크롤 로딩 체인 — 전 품목 44장 자동 적재", $$("#grid .card").length === 44);
ok("대문에 '더 보기' 버튼 없음 (스크롤이 버튼)", $("[data-action=more]") === null);
ok("끝 배지 노출", Boolean($(".pager__end")));
ok("요약줄 총 44건(전체)", $("#resultMeta").textContent.includes("44"));
ok("주소창 파라미터 없음", dom.window.location.search === "");
ok(
  "카드가 진짜 링크(원문 새 탭)",
  $$("#grid .card").every(
    (a) => a.tagName === "A" && a.target === "_blank" && a.href.startsWith("https://"),
  ),
);
await until(() => $('[data-count="bag"]').textContent.includes("40"));
ok("카테고리 카드 건수 — 가방 40", $('[data-count="bag"]').textContent.includes("40"));
ok("카테고리 카드 건수 — 시계 2", $('[data-count="watch"]').textContent.includes("2"));

// --- 2) 대문에서 검색 → 목록 화면 전환, 제목이 검색어 -------------------------
const si = $("#searchInput");
si.value = "롤렉스";
si.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
await sleep(500);
ok(
  "타이핑만으로는 검색이 나가지 않는다",
  $$("#grid .card").length === 44 && body.classList.contains("mode-home"),
);
ok("돋보기 = 실행 버튼(type submit)", $(".search__go")?.type === "submit");

submitSearch(); // 엔터(제출) 시점에만 실행
await until(() => $$("#grid .card").length === 1);
ok("대문 검색(엔터) — 목록 모드 전환", !body.classList.contains("mode-home"));
ok("제목이 검색어로 교체", $("#listTitle").textContent === "'롤렉스'");
ok("전체 스코프 검색 — 롤렉스 1건", $$("#grid .card").length === 1);

$("#searchClear") && click($("#searchClear"));
await until(() => $$("#grid .card").length === 24);
ok("검색 해제 — 제목이 카테고리명(전체) 복귀", $("#listTitle").textContent === "전체");
ok("검색 해제 후에도 목록 모드 유지", !body.classList.contains("mode-home"));

// 전체 스코프 0건 검색 — "수집 전" 오표시 버그의 회귀 방지
si.value = "존재하지않는검색어제발";
si.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
submitSearch();
await until(() => $("#grid .state") !== null);
ok(
  "전체 스코프 검색 0건 — '조건에 맞는 매물 없음' (수집 전 아님)",
  $("#grid .state h3").textContent.includes("조건에 맞는") &&
    !$("#grid .state h3").textContent.includes("수집 전"),
);
click($('#grid [data-action="reset"]'));
await until(() => $$("#grid .card").length === 44);
ok("빈 화면의 초기화 버튼 — 전체 44장 복귀", $$("#grid .card").length === 44);

// --- 3) 가방 카테고리 진입 ----------------------------------------------------
click($('[data-category="bag"]'));
await until(() => $$("#grid .card").length === 40);
ok("가방 — 스크롤 체인으로 40장 전량 (24+16, 요청 2회)", $$("#grid .card").length === 40);
ok("가방 — 총 40건", $("#resultMeta").textContent.includes("40"));
ok("가방 — 제목", $("#listTitle").textContent === "가방");
ok("주소창 cat=bag", dom.window.location.search.includes("cat=bag"));
ok("목록 모드에도 '더 보기' 버튼 없음 (스크롤 로딩 통일)", $("[data-action=more]") === null);
// 카테고리 확장으로 가방 검색 브랜드가 12종이 됐다 — 칩은 전체+12.
ok("브랜드 칩 13개(전체+12)", $$("#brandChips .chip").length === 13);
ok("신규 브랜드 칩 노출(디올)", $$("#brandChips .chip").some((c) => c.dataset.value === "디올"));

// --- 4) 브랜드 필터 ------------------------------------------------------------
click($$("#brandChips .chip").find((c) => c.dataset.value === "샤넬"));
await until(
  () =>
    $$("#grid .card").length > 0 &&
    $$("#grid .badge-brand").every((b) => b.textContent.trim() === "샤넬"),
);
ok(
  "샤넬 필터 — 모든 카드가 샤넬",
  $$("#grid .badge-brand").every((b) => b.textContent.trim() === "샤넬"),
);
ok("샤넬 노출 2건 (향수·판매완료 제외)", $$("#grid .card").length === 2);
ok("주소창에 필터 반영", dom.window.location.search.includes("brand="));
ok("필터 배지 1", $("#filterBadge").textContent === "1");
ok(
  "정제 제목 표시(스팸 꼬리 없음)",
  $$("#grid .card__title").some((t) => t.textContent.includes("보이백")) &&
    $$("#grid .card__title").every((t) => !t.textContent.includes("구찌프라다")),
);

// --- 5) 초기화 → 더보기 → 끝 배지 ---------------------------------------------
click($("#filterReset"));
await until(
  () => dom.window.location.search === "?cat=bag" && $$("#grid .card").length === 40,
);
ok("초기화 후 전량 재적재 (40장)", $$("#grid .card").length === 40);
ok("초기화해도 카테고리는 유지", $("#listTitle").textContent === "가방");
ok("주소창은 cat만 남음", dom.window.location.search === "?cat=bag");
ok("끝 배지 노출", Boolean($(".pager__end")));
ok("가격 미상 카드 렌더", $$(".card__price.unknown").length >= 1);
ok("이미지 없는 매물 자리 표시", $$("#grid .noimg").length >= 1);

// --- 6) 검색 디바운스 + 제목 교체 ----------------------------------------------
si.value = "스피디";
si.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
submitSearch();
await until(
  () => $("#resultMeta").textContent.includes("30") && $$("#grid .card").length === 30,
);
ok("검색 '스피디' — 총 30건, 스크롤 체인 30장", $$("#grid .card").length === 30);
ok("검색 중 제목이 검색어", $("#listTitle").textContent === "'스피디'");
ok("검색어 주소창 반영", decodeURIComponent(dom.window.location.search).includes("스피디"));

click($("#searchClear"));
await until(() => $("#listTitle").textContent === "가방");
ok("검색 해제 — 제목이 카테고리명 복귀", $("#listTitle").textContent === "가방");

// --- 7) 정렬 -------------------------------------------------------------------
ok("정렬 칩 4개", $$("#sortChips .chip").length === 4);
ok("기본 최신순 선택", $("#sortChips .chip.on")?.dataset.value === "latest");

click($$("#sortChips .chip").find((c) => c.dataset.value === "price_asc"));
await until(() => $$("#grid .card__price")[0]?.textContent.includes("890,000"));
ok("최저가순 — 첫 카드 ₩890,000", $$("#grid .card__price")[0].textContent.includes("890,000"));
ok("정렬 주소창 반영", dom.window.location.search.includes("sort=price_asc"));
ok("정렬은 필터 배지에 안 센다", $("#filterBadge").textContent === "");

await until(() => $$("#grid .card").length === 40);
ok(
  "최저가순 마지막은 가격 미상 (NULLS LAST)",
  $$("#grid .card__price").at(-1).classList.contains("unknown"),
);

click($$("#sortChips .chip").find((c) => c.dataset.value === "price_desc"));
await until(() => $$("#grid .card__price")[0]?.textContent.includes("12,400,000"));
ok("최고가순 — 첫 카드 ₩12,400,000", $$("#grid .card__price")[0].textContent.includes("12,400,000"));

// --- 8) 가격 슬라이더 ------------------------------------------------------------
click($("#filterReset"));
await until(() => dom.window.location.search === "?cat=bag");

const hiThumb = $("#rangeMax");
hiThumb.value = "30"; // 스텝 테이블에서 인덱스 30 = 500만원
hiThumb.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
ok("드래그 중 입력칸 실시간 미러링 (500)", $("#maxPrice").value === "500");
ok("드래그 중 라벨 갱신", $("#rangeLabel").textContent.includes("500만원"));

hiThumb.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
await until(() => $("#resultMeta").textContent.includes("34"));
ok("슬라이더 확정 — 500만 이하 34건", $("#resultMeta").textContent.includes("34"));
ok("주소창 max=500", dom.window.location.search.includes("max=500"));

// --- 9) 카테고리 전환 ------------------------------------------------------------
click($("#filterReset"));
await until(() => dom.window.location.search === "?cat=bag");

click($('[data-category="watch"]'));
await until(() => $$("#grid .card").length === 2);
ok("시계 전환 — 카드 2장", $$("#grid .card").length === 2);
ok("시계 전환 — 제목이 목록과 일치", $$("#grid .card__title").every(
  (t) => t.textContent.includes("시계"),
));
ok("주소창 cat=watch", dom.window.location.search.includes("cat=watch"));
ok("목록 제목 갱신", $("#listTitle").textContent === "시계");
const brandChipValues = $$("#brandChips .chip").map((c) => c.dataset.value);
ok("브랜드 칩이 시계 브랜드로 교체", brandChipValues.includes("롤렉스") && !brandChipValues.includes("고야드"));

click($('[data-category="jewelry"]'));
await until(() => $("#grid .state") !== null);
ok("주얼리(0건) — 수집 전 콜드스타트 문구",
   $("#grid .state h3").textContent.includes("주얼리") &&
   $("#grid .state h3").textContent.includes("수집 전"));

click($('[data-category="bag"]'));
await until(() => $$("#grid .card").length === 40);
ok("가방 복귀 — 스크롤 체인 40장", $$("#grid .card").length === 40);


// --- 10) 로고 → 대문 복귀 -------------------------------------------------------
click($$(".home-link")[0]);
ok("로고 클릭 — 대문 모드 복귀", body.classList.contains("mode-home"));
ok("주소 파라미터 제거", dom.window.location.search === "");
ok("제목 '전체' 복귀", $("#listTitle").textContent === "전체");
ok("본문 카드 활성 해제, 헤더는 '전체' 활성",
  $$(".cat.cat--active").length === 0 &&
  $(".tnav__item.cat--active")?.dataset.category === "all");
ok("검색 입력창 비워짐", $("#searchInput").value === "");
await until(() => $$("#grid .card").length === 44);
ok("복귀 후 스크롤 체인 재적재 — 44장", $$("#grid .card").length === 44);


// --- 11) 푸터 고지 · 맨 위로 버튼 -------------------------------------------------
ok(
  "푸터 — 거래 비당사자 고지 존재",
  $(".footer__legal").textContent.includes("통신판매중개자도 아닙니다"),
);
ok(
  "푸터 — 지어낸 사업자 정보 없음",
  !$(".footer__legal").textContent.includes("사업자등록번호"),
);
ok(
  "푸터 — 실존 링크(GitHub)만",
  $$(".footer__links a").every((a) => a.href.startsWith("https://github.com/")),
);

const topBtn = $("#topBtn");
ok("TOP 버튼 — 초기 숨김", !topBtn.classList.contains("on"));
globalThis.scrollY = 900; // main.js가 읽는 곳은 jsdom 창이 아니라 전역이다
dom.window.document.dispatchEvent(new dom.window.Event("scroll"));
ok("TOP 버튼 — 600px 초과 스크롤 시 노출", topBtn.classList.contains("on"));
globalThis.scrollY = 0;
dom.window.document.dispatchEvent(new dom.window.Event("scroll"));
ok("TOP 버튼 — 상단 복귀 시 숨김", !topBtn.classList.contains("on"));


// --- 12) 최상단 헤더 -------------------------------------------------------------
ok("헤더 카테고리 내비 6항목 (전체+5)", $$(".tnav__item").length === 6);

click($$(".tnav__item").find((b) => b.dataset.category === "watch"));
await until(() => $$("#grid .card").length === 2);
ok("헤더 내비 클릭 — 기존 위임으로 시계 전환", $$("#grid .card").length === 2);
ok(
  "헤더 내비 활성 동기화 (카드와 같은 함수)",
  $$(".tnav__item").find((b) => b.dataset.category === "watch").classList.contains("cat--active"),
);

click($('[data-category="bag"]:not(.tnav__item)')); // 본문 카드 클릭
await until(() => $$("#grid .card").length === 40);
ok(
  "카드 클릭이 헤더 내비에도 반영",
  $$(".tnav__item").find((b) => b.dataset.category === "bag").classList.contains("cat--active"),
);

const tip = $("#loginTip");
ok("로그인 안내 — 초기 숨김", tip.hidden === true);
click($("#loginBtn"));
ok("로그인 클릭 — '준비 중' 정직 고지", tip.hidden === false && tip.textContent.includes("준비 중"));


// --- 13) V4 이식분: Reverdi 브랜딩 · 추천 검색어 · 최신 매물 레일 ------------------
ok("워드마크 Reverdi", $(".topbar .wordmark").textContent.replace(/\s+/g, "") === "Reverdi");
ok("추천 검색어 칩 6개", $$(".kwchip").length === 6);

await until(() => $$("#recoViewport .rcard").length > 0);
ok("레일 — 카테고리별 최신 8장 (시드: 가방4+시계2+신발1+의류1, 주얼리0)",
   $$("#recoViewport .rcard").length === 8);
ok("레일 — 카테고리 혼합 증명(시계 뱃지 존재)",
   $$("#recoViewport .rcard__cat").some((b) => b.textContent === "시계"));
ok("레일 카드도 진짜 링크",
   $$("#recoViewport .rcard").every((a) => a.target === "_blank" && a.href.startsWith("https://")));

click($$(".kwchip")[1]); // "롤렉스 서브마리너"
await until(() => !body.classList.contains("mode-home"));
ok("칩 클릭 — 목록 전환 + 제목이 검색어", $("#listTitle").textContent === "'롤렉스 서브마리너'");
ok("칩 클릭 — 입력창 동기화", $("#searchInput").value === "롤렉스 서브마리너");

console.log(`\n결과: ${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
