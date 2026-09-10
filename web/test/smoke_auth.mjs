// 로그인/세션 프론트 회귀 테스트.
// 서버 세션(/api/auth/me)이 화면 상태의 유일한 기준인지 확인한다.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const authUrl = pathToFileURL(resolve(webDir, "js/auth.js")).href;
const homeAuthUrl = pathToFileURL(resolve(webDir, "js/home_auth.js")).href;
const loginUrl = pathToFileURL(resolve(webDir, "js/login.js")).href;

const fails = [];
const check = (name, condition, extra = "") => {
  if (condition) console.log(`  OK   ${name}`);
  else {
    console.log(`  FAIL ${name} ${extra}`);
    fails.push(name);
  }
};

const sleep = (ms = 20) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

let handler = async () => ({ ok: true, status: 200, json: async () => null });
const calls = [];

globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), options });
  return handler(String(url), options);
};

const redirects = [];
globalThis.location = {
  replace(url) {
    redirects.push(String(url));
  },
};

function installDom(html, url = "http://localhost:8000/") {
  const dom = new JSDOM(html, { url, pretendToBeVisual: true });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.sessionStorage = dom.window.sessionStorage;
  return dom;
}

installDom('<a id="loginBtn" href="login.html">로그인</a><div id="accountBar"></div>');

const auth = await import(`${authUrl}?smoke=auth`);

console.log("\n[auth.js 서버 세션 기준]");
sessionStorage.setItem("reverdi_role", "client");
handler = async () => ({ ok: true, status: 200, json: async () => null });
calls.length = 0;

const anonymous = await auth.fetchMe();
check("sessionStorage가 client여도 서버 null이면 비로그인", anonymous === null);
check("서버 null이면 stale role 제거", sessionStorage.getItem("reverdi_role") === null);
check("credentials=same-origin", calls[0]?.options?.credentials === "same-origin");
check("cache=no-store", calls[0]?.options?.cache === "no-store");

handler = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ username: "client", role: "client", display_role: "기업고객" }),
});
const clientMe = await auth.fetchMe();
check("서버 client 반환", clientMe?.role === "client");
check("client role 보조 저장", sessionStorage.getItem("reverdi_role") === "client");

console.log("\n[login/logout]");
handler = async (url, options) => {
  if (url === "/api/auth/login") {
    return {
      ok: true,
      status: 200,
      json: async () => ({ username: "admin", role: "admin", display_role: "관리자" }),
    };
  }
  if (url === "/api/auth/logout") {
    return { ok: true, status: 204, json: async () => null };
  }
  return { ok: true, status: 200, json: async () => null };
};
calls.length = 0;

const loggedIn = await auth.login("admin", "admin1234");
check("login 결과 role", loggedIn.role === "admin");
check("login은 POST", calls[0]?.options?.method === "POST");
check("login role 저장", sessionStorage.getItem("reverdi_role") === "admin");

await auth.logout();
check("logout은 POST", calls.some((c) => c.url === "/api/auth/logout" && c.options.method === "POST"));
check("logout role 제거", sessionStorage.getItem("reverdi_role") === null);

console.log("\n[guard]");
redirects.length = 0;
handler = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ username: "admin", role: "admin", display_role: "관리자" }),
});
const guarded = await auth.guard("client");
check("다른 role이면 null", guarded === null);
check("admin 자기 화면으로 이동", redirects.at(-1) === "admin.html");

console.log("\n[home_auth.js]");
document.body.innerHTML = '<a id="loginBtn" href="login.html">로그인</a>';
handler = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ username: "client", role: "client", display_role: "기업고객" }),
});
await import(`${homeAuthUrl}?smoke=${Date.now()}`);
await sleep();

let accountLink = document.getElementById("loginBtn");
check("client → My Inventory", accountLink.textContent === "My Inventory");
check("client href", accountLink.getAttribute("href") === "client.html");

handler = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ username: "admin", role: "admin", display_role: "관리자" }),
});
window.dispatchEvent(new window.Event("focus"));
await sleep();

accountLink = document.getElementById("loginBtn");
check("focus 후 admin → Console", accountLink.textContent === "Console");
check("admin href", accountLink.getAttribute("href") === "admin.html");

handler = async () => ({ ok: true, status: 200, json: async () => null });
window.dispatchEvent(new window.Event("pageshow"));
await sleep();

accountLink = document.getElementById("loginBtn");
check("pageshow 후 비로그인 → 로그인", accountLink.textContent === "로그인");
check("비로그인 href", accountLink.getAttribute("href") === "login.html");

console.log("\n[login.js 자동 이동]");
redirects.length = 0;
installDom("<main></main>", "http://localhost:8000/login.html");
handler = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ username: "admin", role: "admin", display_role: "관리자" }),
});
await import(`${loginUrl}?case=already-admin-${Date.now()}`);
await sleep();
check("이미 admin 세션이면 Console로 이동", redirects.at(-1) === "admin.html");

console.log("\n[login.js 폼 로그인]");
redirects.length = 0;
const loginHtml = readFileSync(resolve(webDir, "login.html"), "utf8");
installDom(loginHtml, "http://localhost:8000/login.html");

handler = async (url, options) => {
  if (url === "/api/auth/me") {
    return { ok: true, status: 200, json: async () => null };
  }
  if (url === "/api/auth/login") {
    return {
      ok: true,
      status: 200,
      json: async () => ({ username: "client", role: "client", display_role: "기업고객" }),
    };
  }
  throw new Error(`unexpected fetch: ${url} ${options.method || "GET"}`);
};

calls.length = 0;
await import(`${loginUrl}?case=form-${Date.now()}`);
await sleep();

document.getElementById("username").value = "client";
document.getElementById("password").value = "client1234";
document.getElementById("loginForm").dispatchEvent(
  new window.Event("submit", { bubbles: true, cancelable: true }),
);
await sleep();

const loginCall = calls.find((c) => c.url === "/api/auth/login");
check("폼이 /api/auth/login 호출", !!loginCall);
check("폼 로그인 POST", loginCall?.options?.method === "POST");
check("client 로그인 후 My Inventory 이동", redirects.at(-1) === "client.html");

if (fails.length) {
  console.error(`\n${fails.length}개 실패: ${fails.join(", ")}`);
  process.exit(1);
}

console.log("\n모든 로그인/세션 프론트 스모크 테스트 통과");
