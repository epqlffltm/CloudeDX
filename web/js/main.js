// reluxe/js/main.js
//
// 진입점. 흐름은 하나뿐이다:
//   이벤트 → state 변경 → 서버 조회 → renderList(state)
// DOM을 직접 만지는 코드는 render.js에만 있고, 여기는 상태와 배선만 다룬다.

import { fetchListings, fetchMeta } from "./api.js";
import {
  DEFAULT_FILTERS,
  PAGE_SIZE,
  SORT_OPTIONS,
  state,
  readFiltersFromURL,
  writeFiltersToURL,
} from "./state.js";
import {
  renderCategoryCards,
  renderChips,
  renderFilterBadge,
  renderFilterInputs,
  renderList,
  renderMetaLine,
  renderRange,
  renderSheetCTA,
  renderTitle,
  stepIndexFor,
  stepValue,
} from "./render.js";

const $ = (id) => document.getElementById(id);

/* ---------------------------------------------------------------------------
   서버 조회 — 경합 방어가 핵심이다.
   빠르게 타이핑하면 요청 여러 개가 공중에 뜨는데, 늦게 출발한 옛 응답이
   마지막에 도착해 새 결과를 덮는 사고를 AbortController가 막는다.
   React였다면 useEffect cleanup이 하던 그 일이다.
--------------------------------------------------------------------------- */

/**
 * 화면 모드. "home"은 대문(로고·카테고리·검색창, 필터 없음, 스크롤 로딩)이고
 * "list"는 카테고리·검색으로 들어온 목록 화면이다. 파라미터 없는 주소가 대문이다.
 */
function setMode(mode) {
  state.mode = mode;
  document.body.classList.toggle("mode-home", mode === "home");
}

let inflight = null;

async function load({ append = false } = {}) {
  inflight?.abort();
  inflight = new AbortController();

  state.status = append ? "appending" : "loading";
  state.offset = append ? state.offset + PAGE_SIZE : 0;
  if (!append) state.items = [];
  renderList(state);

  try {
    const data = await fetchListings(state.filters, state.offset, PAGE_SIZE, inflight.signal);
    state.items = append ? [...state.items, ...data.items] : data.items;
    state.total = data.total;
    state.hasNext = data.has_next;
    state.status = "ready";
  } catch (err) {
    if (err.name === "AbortError") return; // 더 새 요청이 이겼다 — 조용히 물러난다
    state.status = "error";
    state.errorMessage = err.message;
  }

  renderList(state);
  renderMetaLine(state);
  renderSheetCTA(state);
  armScrollLoader();
}

/** 필터가 바뀌었을 때의 공통 경로: URL 반영 → 배지 → 첫 페이지부터 다시 */
function applyFilters() {
  writeFiltersToURL(state.filters);
  renderFilterBadge(state.filters);
  renderTitle(state.filters);
  load();
}

/** 칩 세 벌을 현재 상태로 다시 그린다. 칩 하나가 바뀌면 전부 다시 — 부분 수정 없음. */
function rerenderChips() {
  // 브랜드 선택지는 카테고리를 따라간다 — 시계 화면에서 고야드 칩은 소음이다.
  const brands =
    state.meta?.brands_by_category?.[state.filters.category] ?? state.meta?.brands ?? [];
  renderChips("brandChips", brands, state.filters.brand, { withAll: true });
  renderChips("sourceChips", state.meta?.sources ?? [], state.filters.source, { withAll: true });
  renderChips("sortChips", SORT_OPTIONS, state.filters.sort);
}

function resetFilters() {
  // 카테고리는 초기화 대상이 아니다 — 시계를 보다가 "필터 초기화"를 눌렀는데
  // 가방으로 튕기면, 초기화가 아니라 이동이 된다.
  state.filters = { ...DEFAULT_FILTERS, category: state.filters.category };
  renderFilterInputs(state.filters);
  rerenderChips();
  applyFilters();
}

/* ---------------------------------------------------------------------------
   바텀시트 열기/닫기 (모바일 전용 — 데스크톱에선 CSS가 버튼째 숨긴다)
--------------------------------------------------------------------------- */

function openSheet() {
  $("filters").classList.add("open");
  $("backdrop").classList.add("on");
  document.body.classList.add("no-scroll");
}

function closeSheet() {
  $("filters").classList.remove("open");
  $("backdrop").classList.remove("on");
  document.body.classList.remove("no-scroll");
}

/* ---------------------------------------------------------------------------
   이벤트 배선
--------------------------------------------------------------------------- */

function wireEvents() {
  // 칩은 계속 다시 그려지므로 개별 바인딩 대신 문서 위임 한 번으로 끝낸다
  document.addEventListener("click", (e) => {
    const home = e.target.closest(".home-link");
    if (home) {
      e.preventDefault(); // 링크의 풀 리로드 대신 소프트 복귀 — JS가 죽으면 링크가 폴백
      goHome();
      return;
    }

    const card = e.target.closest("[data-category]");
    if (card) {
      setMode("list"); // 대문에서 눌렀으면 목록 화면으로 — 이미 목록이면 무해
      const next = card.dataset.category;
      if (next !== state.filters.category) {
        state.filters.category = next;
        // 브랜드 선택지가 카테고리마다 달라서, 안 파는 브랜드가 걸려 있으면 푼다
        const brands = state.meta?.brands_by_category?.[next] ?? [];
        if (state.filters.brand !== "전체" && !brands.includes(state.filters.brand)) {
          state.filters.brand = "전체";
        }
        renderCategoryCards(state.meta, next);
        rerenderChips();
        renderFilterInputs(state.filters); // 미확정 타이핑을 적용값으로 되돌린다
        applyFilters();
      }
      return;
    }

    const chip = e.target.closest("[data-chip]");
    if (chip) {
      const key = { brandChips: "brand", sourceChips: "source", sortChips: "sort" }[
        chip.dataset.chip
      ];
      state.filters[key] = chip.dataset.value;
      rerenderChips();
      applyFilters();
      return;
    }

    const action = e.target.closest("[data-action]")?.dataset.action;
    if (action === "more") load({ append: true });
    if (action === "retry") load();
    if (action === "reset") resetFilters();
  });

  // 검색은 확정 실행이다 — 엔터(submit)나 돋보기 버튼으로만 나간다.
  // 타이핑 자동 검색(디바운스)을 뺀 이유: 의도가 확정되기 전의 요청 낭비와,
  // 글자마다 목록이 출렁이는 조작감 문제. 서버 search는 원제목 대상이라
  // 정제 제목만 보이는 화면에서 검색어가 안 보일 수 있다 — 의도된 비대칭이다.
  const searchInput = $("searchInput");
  searchInput.addEventListener("input", () => {
    // 실행은 안 하고 X 버튼 표시만 갱신한다
    searchInput.closest(".search").classList.toggle("has-value", Boolean(searchInput.value));
  });

  $("searchForm").addEventListener("submit", (e) => {
    e.preventDefault(); // 페이지 새로고침 막기 — 제출이 곧 검색 실행
    state.filters.q = searchInput.value.trim();
    if (state.filters.q && state.mode === "home") setMode("list");
    applyFilters();
    searchInput.blur(); // 모바일 키보드 내리기
  });

  $("searchClear").addEventListener("click", () => {
    searchInput.value = "";
    searchInput.closest(".search").classList.remove("has-value");
    state.filters.q = "";
    applyFilters();
  });

  // 가격 — 타이핑마다가 아니라 확정(blur/Enter) 시점에 적용한다.
  // "3"을 치는 순간 300만원 필터가 걸리는 화면은 조작감이 아니라 방해다.
  const readPrice = (input) => {
    const n = Number(input.value);
    return input.value !== "" && Number.isFinite(n) && n >= 0 ? n : null;
  };
  for (const id of ["minPrice", "maxPrice"]) {
    $(id).addEventListener("change", () => {
      state.filters.min = readPrice($("minPrice"));
      state.filters.max = readPrice($("maxPrice"));
      // 슬라이더는 근사 위치로 따라온다. 필터값은 입력칸의 정밀값이 정본이다.
      renderRange(
        stepIndexFor(state.filters.min, "min"),
        stepIndexFor(state.filters.max, "max"),
      );
      applyFilters();
    });
  }

  // 슬라이더 — 드래그 중(input)에는 시각만 갱신하고, 놓는 시점(change)에 적용한다.
  // 드래그마다 서버를 부르면 요청이 튀고, AbortController가 있어도 낭비는 낭비다.
  const readRangeIdx = () => {
    let lo = Number($("rangeMin").value);
    let hi = Number($("rangeMax").value);
    if (lo > hi) [lo, hi] = [hi, lo]; // 썸 교차 방지 — 잡은 쪽이 상대를 넘으면 서로 맞바꾼다
    return [lo, hi];
  };

  for (const id of ["rangeMin", "rangeMax"]) {
    $(id).addEventListener("input", () => {
      const [lo, hi] = readRangeIdx();
      renderRange(lo, hi);
      // 입력칸에도 실시간으로 비춘다. 프로그램으로 넣는 값은 change를 안 일으키므로
      // 여기서 fetch가 나가지는 않는다.
      $("minPrice").value = stepValue(lo, "min") || "";
      $("maxPrice").value = stepValue(hi, "max") ?? "";
    });
    $(id).addEventListener("change", () => {
      const [lo, hi] = readRangeIdx();
      state.filters.min = lo === 0 ? null : stepValue(lo, "min");
      state.filters.max = stepValue(hi, "max");
      applyFilters();
    });
  }

  $("filterReset").addEventListener("click", resetFilters);
  $("filterOpen").addEventListener("click", openSheet);
  $("filterClose").addEventListener("click", closeSheet);
  $("backdrop").addEventListener("click", closeSheet);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSheet();
  });

  // 로그인 — 백엔드가 아직 없다. 가짜 폼 대신 준비 중임을 짧게 알린다.
  let loginTipTimer;
  $("loginBtn").addEventListener("click", () => {
    const tip = $("loginTip");
    tip.hidden = false;
    clearTimeout(loginTipTimer);
    loginTipTimer = setTimeout(() => {
      tip.hidden = true;
    }, 2500);
  });

  // 맨 위로 버튼 — 600px 넘게 내려가면 나타난다. scroll은 고빈도 이벤트라
  // passive로 달고, 하는 일은 클래스 토글 하나뿐이라 스로틀 없이도 싸다.
  const topBtn = $("topBtn");
  document.addEventListener(
    "scroll",
    () => topBtn.classList.toggle("on", (globalThis.scrollY ?? 0) > 600),
    { passive: true },
  );
  topBtn.addEventListener("click", () => {
    globalThis.scrollTo?.({ top: 0, behavior: "smooth" });
  });

  // 이미지 로드 실패(핫링크 차단·삭제)는 자리만 남기고 '이미지 없음'으로.
  // error 이벤트는 버블링하지 않으므로 캡처 단계에서 위임한다.
  document.addEventListener(
    "error",
    (e) => {
      const img = e.target;
      if (img.tagName === "IMG" && img.closest(".card__thumb")) {
        img.replaceWith(Object.assign(document.createElement("span"), {
          className: "noimg",
          textContent: "이미지 없음",
        }));
      }
    },
    true,
  );
}

/**
 * 대문 복귀. 로고를 눌렀을 때 첫 진입(/)과 같은 상태로 돌아간다 —
 * 필터 전부 기본값, 파라미터 없는 주소, 스크롤 로딩 대기.
 */
function goHome() {
  inflight?.abort(); // 날아가던 목록 요청은 이제 무의미하다
  closeSheet();
  state.filters = { ...DEFAULT_FILTERS };
  state.items = [];
  state.total = 0;
  state.hasNext = false;
  state.status = "idle";
  setMode("home");
  history.replaceState(null, "", location.pathname);
  renderCategoryCards(state.meta, state.filters.category);
  renderTitle(state.filters);
  renderFilterInputs(state.filters);
  renderFilterBadge(state.filters);
  rerenderChips();
  renderList(state);
  renderMetaLine(state);
  globalThis.scrollTo?.({ top: 0, behavior: "smooth" });
  armScrollLoader();
}

/* ---------------------------------------------------------------------------
   대문 스크롤 로딩 — 목록 영역(pager)이 뷰포트에 다가오면 다음 페이지를 얹는다.
   버튼("더 보기")은 목록 모드에 그대로 남는다 — 대문에서만 스크롤이 곧 버튼이다.
--------------------------------------------------------------------------- */

const scrollLoader =
  "IntersectionObserver" in globalThis
    ? new IntersectionObserver(
        (entries) => {
          if (!entries.some((e) => e.isIntersecting)) return;
          if (state.status === "idle" && state.items.length === 0) {
            load(); // 대문의 첫 로드 — 목록 영역이 다가오는 순간
          } else if (state.status === "ready" && state.hasNext) {
            load({ append: true });
          }
        },
        { rootMargin: "400px" },
      )
    : null;

state.autoLoad = scrollLoader !== null;

/**
 * 옵저버 재장전 — 대문·목록 공통. 로드가 끝난 뒤 sentinel(#pager)이 여전히
 * 화면 안이면 콜백이 즉시 다시 오므로, 화면이 찰 때까지 자연스럽게 이어 붙는다.
 * IntersectionObserver가 없는 환경(구형 브라우저)에서는 대문의 첫 페이지만
 * 바로 부르고, 이후는 렌더가 그려주는 "더 보기" 버튼이 스크롤을 대신한다.
 */
function armScrollLoader() {
  if (!scrollLoader) {
    if (state.mode === "home" && state.status === "idle") load();
    return;
  }
  const pager = $("pager");
  scrollLoader.unobserve(pager);
  if (state.status === "idle" || (state.status === "ready" && state.hasNext)) {
    scrollLoader.observe(pager);
  }
}

/* ---------------------------------------------------------------------------
   시작
--------------------------------------------------------------------------- */

async function init() {
  state.filters = readFiltersFromURL();
  // 파라미터 없는 주소가 대문이다. cat·검색어·필터 무엇이든 있으면 목록 화면.
  setMode(location.search.length > 1 ? "list" : "home");
  renderCategoryCards(null, state.filters.category);
  renderTitle(state.filters);
  renderFilterInputs(state.filters);
  renderFilterBadge(state.filters);
  // meta 도착 전에도 칩 골격은 보여준다 (브랜드·플랫폼은 전체만, 정렬은 완성형)
  rerenderChips();
  wireEvents();

  // 대문은 스크롤이 트리거다 — 목록 영역이 다가올 때 첫 로드가 뜬다.
  // 목록 모드는 기존처럼 즉시 부른다. meta는 어느 쪽이든 병렬 출발.
  if (state.mode === "home") {
    state.status = "idle";
    renderList(state);
    armScrollLoader();
  } else {
    load();
  }
  try {
    state.meta = await fetchMeta();
    renderCategoryCards(state.meta, state.filters.category);
    rerenderChips();
    renderMetaLine(state);
    renderList(state); // 빈 화면 문구가 meta(콜드스타트 여부)에 걸려 있어 한 번 더
  } catch {
    // meta가 죽어도 목록은 살 수 있다. 칩 선택지와 카드 건수만 없는 채로 동작한다.
    renderCategoryCards(null, state.filters.category);
  }
}

init();
