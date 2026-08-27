// 새 프론트가 API 응답으로 실제 화면을 그리는지 확인한다.
// jsdom은 <script type="module">을 실행하지 않으므로, 모듈을 직접 import 해서
// 같은 전역(window/document/fetch)을 쓰게 만든다.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

// 경로는 이 파일 위치에서 푼다. 어느 디렉터리에서 실행해도 같게 동작한다.
const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const html = readFileSync(resolve(webDir, "index.html"), "utf8");

const META = {
  sources: ["당근마켓", "중고나라", "번개장터"],
  brands: ["샤넬", "구찌", "루이비통", "롤렉스", "까르띠에"],
  categories: { bag: 1240, watch: 318, jewelry: 96, apparel: 41, shoes: 25 },
  brands_by_category: {
    bag: ["샤넬", "구찌", "루이비통"],
    watch: ["롤렉스", "까르띠에"],
    jewelry: ["까르띠에"],
    apparel: ["구찌"],
    shoes: ["구찌"],
  },
  total_items: 1720,
  last_crawled_at: "2026-08-26T22:10:00Z",
  crawler: { is_running: false, stale: false, rounds_completed: 12, interval_minutes: 60 },
};

const ITEMS = [
  { id: 1, source: "중고나라", title: "롤렉스 서브마리너 124060", brand: "롤렉스",
    category: "watch", price: 17_200_000, image_url: "https://img.test/a.jpg", item_url: "https://ex.test/w1", is_authenticated: true },
  { id: 2, source: "번개장터", title: "샤넬 클래식 미디움 <캐비어>", brand: "샤넬",
    category: "bag", price: null, image_url: null, item_url: "https://ex.test/b1", is_authenticated: false },
  { id: 3, source: "당근마켓", title: "구찌 마몬트 스몰", brand: "구찌",
    category: "bag", price: 1_450_000, image_url: null, item_url: "https://ex.test/b2", is_authenticated: false },
];

const calls = [];

const vc = new VirtualConsole();
vc.on("jsdomError", (e) => { if (!/Could not load/.test(e.message)) console.error("[jsdom]", e.message); });

const dom = new JSDOM(html, {
  url: "http://localhost:8000/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
  virtualConsole: vc,
});

const { window } = dom;

window.fetch = async (url) => {
  calls.push(String(url));
  if (String(url).includes("/api/live/search")) {
    return { ok: true, status: 200, json: async () => ({ status: "saved", saved: 4, keyword: "샤넬 클래식" }) };
  }
  const body = String(url).includes("/api/meta") ? META : {
    total: 1720, count: ITEMS.length, limit: 30, offset: 0, has_next: true, items: ITEMS,
  };
  return { ok: true, status: 200, json: async () => body };
};
window.scrollTo = () => {};

globalThis.window = window;
globalThis.document = window.document;
globalThis.fetch = window.fetch;
globalThis.history = window.history;
globalThis.location = window.location;
globalThis.AbortController = window.AbortController ?? AbortController;
globalThis.Intl = Intl;

await import(pathToFileURL(resolve(webDir, "js/home.js")).href);
await new Promise((r) => setTimeout(r, 120));

const $ = (id) => window.document.getElementById(id);
const fails = [];
const check = (name, cond, extra = "") => {
  if (cond) console.log(`  OK   ${name}`);
  else { console.log(`  FAIL ${name} ${extra}`); fails.push(name); }
};

console.log("\n[대문]");
check("카테고리 5칸이 meta로 그려짐", $("catGrid").querySelectorAll(".cat-item").length === 5);
check("카테고리에 건수 표시", $("catGrid").textContent.includes("1,240건"));
check("가방 라벨 한글화", $("catGrid").textContent.includes("가방"));
check("브랜드 모노그램 5개", $("brandScroll").querySelectorAll(".brand-item").length === 5);
check("브랜드 영문 표기", $("brandScroll").textContent.includes("CHANEL"));
check("상단 내비에 카테고리", $("mainNav").querySelectorAll("button").length === 6);
check("레일에 카드 3장", $("railGrid").querySelectorAll(".p-card").length === 3);
check("히어로 이미지 주입", !!$("hero").querySelector("img"));
check("마지막 수집 시각", $("lastCrawled").textContent.length > 0);

console.log("\n[카드]");
const rail = $("railGrid").innerHTML;
check("가격 천단위 포맷", rail.includes("17,200,000원"));
check("가격 미상 처리", rail.includes("가격 미상"));
check("수집처 뱃지", rail.includes("당근마켓"));
check("제목 이스케이프", rail.includes("&lt;캐비어&gt;") && !rail.includes("<캐비어>"));
check("바깥 링크 rel", rail.includes('rel="noopener noreferrer"'));
check("이미지 없는 매물 처리", rail.includes("이미지 없음"));
check("인증 매물에 씰 1개", (rail.match(/p-seal/g) || []).length === 1);
check("비인증 매물엔 씰 없음", (rail.match(/정품인증/g) || []).length === 1);

console.log("\n[인증 물품 탭]");
const authTab = window.document.querySelector('[data-rail="authenticated"]');
check("인증 탭 존재", !!authTab);
authTab?.dispatchEvent(new window.Event("click", { bubbles: true }));
await new Promise((r) => setTimeout(r, 120));
check("authenticated_only 쿼리 전달", calls.some((c) => c.includes("authenticated_only=true")));
check("탭 선택 상태 전환", authTab?.getAttribute("aria-selected") === "true");

console.log("\n[검색 → 결과 화면]");
$("searchInput").value = "샤넬 클래식";
$("searchForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await new Promise((r) => setTimeout(r, 120));

check("리스트 모드 전환", window.document.body.className === "mode-list");
check("결과 제목", $("resultTitle").textContent.includes("샤넬 클래식"));
check("총 건수", $("resultCount").textContent.includes("1,720"));
check("결과 그리드", $("resultGrid").querySelectorAll(".p-card").length === 3);
check("페이저 다음 활성", !$("pager").querySelector('[data-page="next"]').disabled);
check("페이저 이전 비활성", $("pager").querySelector('[data-page="prev"]').disabled);
check("주소창 반영", window.location.search.includes("q=%EC%83%A4%EB%84%AC") || window.location.search.includes("view=list"));

console.log("\n[실시간 조회]");
check("live 엔드포인트 호출", calls.some((c) => c.includes("/api/live/search")));
check("검색어 전달", calls.some((c) => c.includes("q=")));
check("저장 후 목록 재조회", calls.filter((c) => c.includes("/api/products")).length >= 3);

console.log("\n[필터]");
const brandChip = [...$("brandChips").querySelectorAll(".chip")].find((c) => c.dataset.brand === "샤넬");
check("브랜드 칩 존재", !!brandChip);
brandChip?.dispatchEvent(new window.Event("click", { bubbles: true }));
await new Promise((r) => setTimeout(r, 120));
check("브랜드 칩 활성 표시", brandChip?.getAttribute("aria-pressed") === "true"
  || [...$("brandChips").querySelectorAll(".chip")].some((c) => c.getAttribute("aria-pressed") === "true"));

console.log("\n[API 호출]");
const uniq = [...new Set(calls.map((c) => c.split("?")[0]))];
console.log("  호출 경로:", uniq.join(", "));
check("meta 호출", uniq.includes("/api/meta"));
check("products 호출", uniq.includes("/api/products"));
check("brand 쿼리 전달", calls.some((c) => c.includes("brand=")));
check("search 쿼리 전달", calls.some((c) => c.includes("search=")));
check("order_by 전달", calls.some((c) => c.includes("order_by=")));

console.log(fails.length === 0 ? "\n전부 통과\n" : `\n실패 ${fails.length}건: ${fails.join(", ")}\n`);
process.exit(fails.length === 0 ? 0 : 1);
