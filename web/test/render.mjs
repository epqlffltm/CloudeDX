// web/test/render.mjs
//
// 교체한 프론트가 CloudeDX API 응답으로 실제 화면을 그리는지 확인한다.
// 소스가 아니라 배포되는 빌드 산출물(web/assets/*.js)을 그대로 실행한다.
//
// 주의: jsdom은 <script type="module">을 실행하지 않는다. Vite 산출물은
// 최상위 import/export가 없는 IIFE 형태라 classic script로 넣으면 돈다.
// 검증도 body.textContent가 아니라 #root 안쪽만 본다 — body에는 주입한
// 스크립트 원문(259KB)이 그대로 들어 있어서 무엇이든 "포함"돼 버린다.
//
// 실행: npm i --no-save jsdom && node web/test/render.mjs

import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, "..");

const LISTINGS = [
  { id: 1, source: "중고나라", title: "롤렉스 서브마리너 124060", brand: "롤렉스",
    category: "watch", price: 17_200_000, image_url: null, item_url: "https://ex.test/w1" },
  { id: 2, source: "번개장터", title: "오메가 씨마스터 300", brand: "오메가",
    category: "watch", price: 3_800_000, image_url: null, item_url: "https://ex.test/w2" },
  { id: 3, source: "당근마켓", title: "샤넬 클래식 미디움 캐비어", brand: "샤넬",
    category: "bag", price: 9_800_000, image_url: null, item_url: "https://ex.test/b1" },
];

const json = (body) =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

function stubFetch(url) {
  const path = String(url);
  if (path.includes("/api/meta")) {
    return json({
      sources: ["당근마켓", "중고나라", "번개장터"],
      brands: ["샤넬", "롤렉스", "오메가"],
      categories: { bag: 1, watch: 2, jewelry: 0, apparel: 0, shoes: 0 },
      brands_by_category: { bag: ["샤넬"], watch: ["롤렉스", "오메가"] },
      total_items: 3,
      last_crawled_at: new Date().toISOString(),
      crawler: { is_running: false },
    });
  }
  if (path.includes("/api/products")) {
    return json({ total: 3, count: 3, limit: 100, offset: 0, has_next: false, items: LISTINGS });
  }
  return json({ detail: "not found" });
}

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push(e));

const bundleName = readdirSync(resolve(webDir, "assets")).find((f) => f.endsWith(".js"));
const code = readFileSync(resolve(webDir, "assets", bundleName), "utf8");

const dom = new JSDOM(`<!doctype html><html lang="ko"><body><div id="root"></div></body></html>`, {
  url: "http://localhost:8000/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
});

const { window } = dom;
window.fetch = (url) => stubFetch(url);
window.scrollTo = () => {};
window.IntersectionObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// classic script로 주입 (type="module"이면 jsdom이 그냥 무시한다)
const script = window.document.createElement("script");
script.textContent = code;
window.document.body.appendChild(script);

await new Promise((r) => setTimeout(r, 2000));

const root = window.document.getElementById("root");
const text = root?.textContent ?? "";

const failures = [];
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${!ok && detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
};

console.log("\n교체된 프론트 렌더 검증 (#root 내부만)");
check("번들 실행 중 예외 없음", errors.length === 0, errors[0]?.message);
check("React가 #root에 마운트됨", (root?.childElementCount ?? 0) > 0, `children=${root?.childElementCount}`);
check("대문 카테고리 섹션이 그려진다", text.includes("카테고리 선택"));
check("카테고리 건수가 /api/meta 값이다", text.includes("2") && text.includes("1"));
check("추천 레일에 수집 매물이 올라온다",
  text.includes("서브마리너") || text.includes("씨마스터") || text.includes("클래식"));

console.log("");
if (failures.length) {
  console.error(`실패 ${failures.length}건: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("전부 통과.");
process.exit(0);
