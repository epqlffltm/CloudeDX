// web/js/main.js
//
// 진입점. 흐름은 하나뿐이다:
//     이벤트 → state 변경 → 서버 조회 → 다시 그리기
// DOM을 직접 만지는 코드는 render.js에만 있고, 여기는 상태와 배선만 다룬다.

import { fetchListings, fetchMeta, fetchReco } from './api.js';
import { fetchMe, logout } from './auth.js';
import {
  DEFAULT_FILTERS,
  PAGE_SIZE,
  PRICE_CAP,
  PRICE_PRESETS,
  PRICE_UNLIMITED,
  SORT_OPTIONS,
  readFiltersFromURL,
  state,
  toDisplayBrand,
  writeFiltersToURL,
} from './state.js';
import {
  renderCategoryCards,
  renderChips,
  renderFilterTitle,
  renderList,
  renderPopular,
  renderPresets,
  renderPriceInputs,
  renderPriceStats,
  renderReco,
  renderResultHeader,
  renderSearchInputs,
  renderTabs,
} from './render.js';

const $ = (id) => document.getElementById(id);

/**
 * 선택적 요소 배선. 요소가 없으면 경고만 남기고 넘어간다.
 * 마크업 하나가 빠졌다고 뒤따르는 배선 전부가 죽으면 안 된다.
 */
function on(id, type, handler, options) {
  const node = $(id);

  if (!node) {
    console.warn(`[wire] #${id} 요소가 없어 ${type} 배선을 건너뜁니다.`);
    return null;
  }

  node.addEventListener(type, handler, options);
  return node;
}

/* ---------------------------------------------------------------- 화면 모드 */

function setMode(mode) {
  state.mode = mode;
  document.body.classList.toggle('mode-home', mode === 'home');
  document.body.classList.toggle('mode-list', mode === 'list');
}

/* ------------------------------------------------------------------ 조회 */

// 빠르게 조작하면 요청 여러 개가 공중에 뜬다. 늦게 출발한 옛 응답이 마지막에
// 도착해 새 결과를 덮는 사고를 AbortController가 막는다.
let inflight = null;

async function load({ append = false } = {}) {
  inflight?.abort();
  inflight = new AbortController();

  state.status = append ? 'appending' : 'loading';
  state.offset = append ? state.offset + PAGE_SIZE : 0;
  if (!append) state.items = [];

  renderList(state);

  try {
    const data = await fetchListings(state.filters, state.offset, PAGE_SIZE, inflight.signal);

    state.items = append ? [...state.items, ...data.items] : data.items;
    state.total = data.total;
    state.hasNext = data.has_next;
    state.status = 'ready';
  } catch (err) {
    if (err.name === 'AbortError') return; // 더 새 요청이 이겼다 — 조용히 물러난다
    state.status = 'error';
    state.errorMessage = err.message;
  }

  renderList(state);
  renderResultHeader(state);
  renderPriceStats(state.items);
  armScrollLoader();
}

/* ------------------------------------------------------------ 무한 스크롤 */

/**
 * 목록 끝(#pager)이 화면에 다가오면 다음 장을 얹는다.
 *
 * rootMargin을 400px 준 이유: 사용자가 바닥에 닿은 뒤에 요청이 나가면 로딩
 * 문구를 보는 시간이 생긴다. 한 화면 못 미쳐 미리 부르면 끊김 없이 이어진다.
 *
 * 조회 중(loading/appending)에는 아무것도 하지 않는다. 관찰 콜백은 스크롤 중
 * 여러 번 오는데, 그때마다 부르면 같은 offset을 중복 요청한다.
 */
const scrollLoader =
  'IntersectionObserver' in globalThis
    ? new IntersectionObserver(
        (entries) => {
          if (!entries.some((e) => e.isIntersecting)) return;
          if (state.status !== 'ready' || !state.hasNext) return;
          load({ append: true });
        },
        { rootMargin: '400px' },
      )
    : null;

state.autoLoad = scrollLoader !== null;

/**
 * 옵저버 재장전. 로드가 끝난 뒤에도 sentinel이 화면 안에 있으면 콜백이 즉시
 * 다시 오므로, 화면이 찰 때까지 자연스럽게 이어 붙는다.
 */
function armScrollLoader() {
  if (!scrollLoader) return;

  const pager = $('pager');
  if (!pager) return;

  scrollLoader.unobserve(pager);

  if (state.status === 'ready' && state.hasNext) {
    scrollLoader.observe(pager);
  }
}

/** 필터가 바뀌었을 때의 공통 경로: URL 반영 → 패널 다시 그리기 → 첫 페이지부터 */
function applyFilters() {
  writeFiltersToURL(state.filters);
  renderFilterTitle(state.filters.category);
  renderTabs(state.filters.category);
  renderPresets(state.filters);
  renderPriceInputs(state.filters);
  rerenderChips();
  load();
}

/** 칩 세 벌을 현재 상태로 다시 그린다. 하나가 바뀌면 전부 다시 — 부분 수정 없음. */
function rerenderChips() {
  // 브랜드 선택지는 카테고리를 따라간다 — 시계 화면에서 고야드 칩은 소음이다.
  const raw =
    state.meta?.brands_by_category?.[state.filters.category] ?? state.meta?.brands ?? [];

  renderChips('brandChips', raw.map(toDisplayBrand), state.filters.brand, { withAll: true });
  renderChips('sourceChips', state.meta?.sources ?? [], state.filters.source, { withAll: true });
  renderChips('sortChips', SORT_OPTIONS, state.filters.sort);
}

function resetFilters() {
  // 카테고리는 초기화 대상이 아니다 — 시계를 보다가 "필터 초기화"를 눌렀는데
  // 전체로 튕기면 초기화가 아니라 이동이 된다.
  state.filters = { ...DEFAULT_FILTERS, category: state.filters.category };
  renderSearchInputs('');
  applyFilters();
}

/** 검색 실행 공통 경로 — 대문 히어로와 결과 화면 두 폼이 같은 문을 쓴다. */
function runSearch(raw) {
  state.filters.q = String(raw ?? '').trim();
  if (state.mode === 'home') setMode('list');
  renderSearchInputs(state.filters.q);
  renderPopular('heroPopular', state.filters.q);
  renderPopular('listPopular', state.filters.q);
  applyFilters();
}

/** 카테고리 선택. 대문에서 눌렀으면 결과 화면으로 넘어간다. */
function selectCategory(next) {
  if (state.mode === 'home') setMode('list');
  if (next === state.filters.category) return;

  state.filters.category = next;

  // 카테고리마다 브랜드가 달라서, 안 파는 브랜드가 걸려 있으면 푼다
  const brands = (state.meta?.brands_by_category?.[next] ?? []).map(toDisplayBrand);
  if (state.filters.brand !== '전체' && !brands.includes(state.filters.brand)) {
    state.filters.brand = '전체';
  }

  applyFilters();
  globalThis.scrollTo?.({ top: 0, behavior: 'smooth' });
}

/** 대문 복귀. 첫 진입(/)과 같은 상태로 되돌린다. */
function goHome() {
  inflight?.abort();
  state.filters = { ...DEFAULT_FILTERS };
  state.items = [];
  state.total = 0;
  setMode('home');
  history.replaceState(null, '', location.pathname);
  renderSearchInputs('');
  renderPopular('heroPopular', '');
  renderPopular('listPopular', '');
  renderCategoryCards(state.meta);
  globalThis.scrollTo?.({ top: 0, behavior: 'smooth' });
}

/* ------------------------------------------------------------------ 가격 */

const clampPrice = (v) => Math.max(0, Math.min(v, PRICE_UNLIMITED));

/** 입력칸(만원) → 필터(원). 빈 칸은 "제한 없음"이다. */
function readPriceInputs() {
  const raw = (id) => {
    const v = $(id)?.value;
    if (v === '' || v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n * 10_000 : null;
  };

  state.filters.min = clampPrice(raw('minPrice') ?? 0);
  state.filters.max = clampPrice(raw('maxPrice') ?? PRICE_UNLIMITED);

  // 뒤집힌 입력은 서버가 422로 막는다. 그 전에 여기서 맞바꾼다.
  if (state.filters.min > state.filters.max) {
    [state.filters.min, state.filters.max] = [state.filters.max, state.filters.min];
  }
}

/** 슬라이더 → 필터. 상한에 닿으면 "제한 없음"으로 해석한다. */
function readRange() {
  let lo = Number($('rangeMin')?.value ?? 0);
  let hi = Number($('rangeMax')?.value ?? PRICE_CAP);

  if (lo > hi) [lo, hi] = [hi, lo]; // 썸 교차 방지

  state.filters.min = lo;
  state.filters.max = hi >= PRICE_CAP ? PRICE_UNLIMITED : hi;
}

/* ------------------------------------------------------------------ 배선 */

function wireEvents() {
  // 칩·탭·카드는 계속 다시 그려지므로 개별 바인딩 대신 문서 위임 한 번으로 끝낸다
  document.addEventListener('click', (e) => {
    const home = e.target.closest('.home-link');
    if (home) {
      e.preventDefault(); // 풀 리로드 대신 소프트 복귀 — JS가 죽으면 링크가 폴백
      goHome();
      return;
    }

    const kw = e.target.closest('[data-kw]');
    if (kw) { runSearch(kw.dataset.kw); return; }

    const cat = e.target.closest('[data-category]');
    if (cat) {
      closeMega();
      selectCategory(cat.dataset.category);
      return;
    }

    const chip = e.target.closest('[data-chip]');
    if (chip) {
      const key = { brandChips: 'brand', sourceChips: 'source', sortChips: 'sort' }[chip.dataset.chip];
      state.filters[key] = chip.dataset.value;
      applyFilters();
      return;
    }

    const preset = e.target.closest('[data-preset]');
    if (preset) {
      const p = PRICE_PRESETS[Number(preset.dataset.preset)];
      state.filters.min = p.min;
      state.filters.max = p.max;
      applyFilters();
      return;
    }

    const dot = e.target.closest('[data-recodot]');
    if (dot) {
      state.reco.page = Number(dot.dataset.recodot);
      renderReco(state.reco);
      return;
    }

    const nav = e.target.closest('[data-reco]');
    if (nav) {
      const pages = Math.max(Math.ceil(state.reco.items.length / state.reco.pageSize), 1);
      const step = nav.dataset.reco === 'prev' ? -1 : 1;
      state.reco.page = (state.reco.page + step + pages) % pages;
      renderReco(state.reco);
      return;
    }

    const clear = e.target.closest('[data-clear]');
    if (clear) { runSearch(''); return; }

    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'more') load({ append: true });
    if (action === 'retry') load();
    if (action === 'reset') resetFilters();
  });

  // 검색은 확정 실행이다 — 엔터(submit)나 돋보기 버튼으로만 나간다.
  // 타이핑 자동 검색을 뺀 이유: 의도가 확정되기 전의 요청 낭비와, 글자마다
  // 목록이 출렁이는 조작감 문제.
  for (const [formId, inputId] of [['searchForm', 'searchInput'], ['heroSearchForm', 'heroSearchInput']]) {
    on(formId, 'submit', (e) => {
      e.preventDefault();
      const input = $(inputId);
      runSearch(input?.value ?? '');
      input?.blur(); // 모바일 키보드 내리기
    });

    on(inputId, 'input', () => {
      const input = $(inputId);
      input?.closest('.search')?.classList.toggle('has-value', Boolean(input.value));
    });
  }

  // 가격 입력칸 — 타이핑마다가 아니라 확정(change) 시점에 적용한다.
  // "3"을 치는 순간 3만원 필터가 걸리는 화면은 조작감이 아니라 방해다.
  for (const id of ['minPrice', 'maxPrice']) {
    on(id, 'change', () => {
      readPriceInputs();
      applyFilters();
    });
  }

  // 슬라이더 — 드래그 중(input)에는 시각만 갱신하고, 놓는 시점(change)에 조회한다.
  // 드래그마다 서버를 부르면 요청이 튄다.
  for (const id of ['rangeMin', 'rangeMax']) {
    on(id, 'input', () => {
      readRange();
      renderPriceInputs(state.filters);
      renderPresets(state.filters);
    });
    on(id, 'change', () => {
      readRange();
      applyFilters();
    });
  }

  on('filterReset', 'click', resetFilters);
  on('filters', 'submit', (e) => e.preventDefault());

  on('megaToggle', 'click', () => {
    const menu = $('megaMenu');
    const open = !menu.classList.contains('open');
    menu.classList.toggle('open', open);
    $('megaToggle').setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-hidden', String(!open));
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeMega();
  });

  // 로그인 / 마이페이지. 비로그인이면 로그인 화면으로, 로그인 상태면
  // 역할에 맞는 페이지로 보낸다. 상태는 renderAccount()가 채워둔다.
  on('loginBtn', 'click', async () => {
    if (!me) { location.href = 'login.html'; return; }
    await logout();
    me = null;
    renderAccount();
  });

  on('myPageBtn', 'click', () => {
    location.href = me ? (me.role === 'admin' ? 'admin.html' : 'client.html') : 'login.html';
  });

  // 맨 위로 — scroll은 고빈도 이벤트라 passive로 달고, 하는 일은 클래스 토글뿐이다.
  const topBtn = $('topBtn');
  document.addEventListener(
    'scroll',
    () => topBtn?.classList.toggle('on', (globalThis.scrollY ?? 0) > 600),
    { passive: true },
  );
  on('topBtn', 'click', () => globalThis.scrollTo?.({ top: 0, behavior: 'smooth' }));

  // 이미지 로드 실패(핫링크 차단·삭제)는 자리만 남기고 '이미지 없음'으로.
  // error 이벤트는 버블링하지 않으므로 캡처 단계에서 위임한다.
  document.addEventListener(
    'error',
    (e) => {
      const img = e.target;
      if (img.tagName === 'IMG' && img.closest('.card__thumb')) {
        img.replaceWith(
          Object.assign(document.createElement('span'), {
            className: 'noimg',
            textContent: '이미지 없음',
          }),
        );
      }
    },
    true,
  );
}

/* ------------------------------------------------------------------ 계정 */

// 지금 로그인한 사람. 비로그인은 null. 상단바 표기만 바꾸는 용도다 —
// 실제 권한 판정은 서버가 한다(app/auth.py의 require_role).
let me = null;

function renderAccount() {
  const loginBtn = $('loginBtn');
  const myPageBtn = $('myPageBtn');
  const tip = $('loginTip');

  if (!loginBtn || !myPageBtn) return;

  loginBtn.querySelector('span').textContent = me ? '로그아웃' : '로그인';
  myPageBtn.querySelector('span').textContent = me ? me.display_role : '마이페이지';

  if (tip) {
    tip.hidden = !me;
    if (me) tip.textContent = me.username;
  }
}

function closeMega() {
  const menu = $('megaMenu');
  if (!menu) return;
  menu.classList.remove('open');
  $('megaToggle')?.setAttribute('aria-expanded', 'false');
  menu.setAttribute('aria-hidden', 'true');
}

/* ------------------------------------------------------------------ 시작 */

async function init() {
  state.filters = readFiltersFromURL();
  // 파라미터 없는 주소가 대문이다. cat·검색어·필터 무엇이든 있으면 결과 화면.
  setMode(location.search.length > 1 ? 'list' : 'home');

  // 초기 렌더는 meta 없이도 되는 골격이다. 여기서 예외가 나도 목록은 떠야 하므로
  // 감싸둔다 — 예전에 이 구간에서 터져 화면이 통째로 백지가 된 적이 있다.
  try {
    renderCategoryCards(null);
    renderTabs(state.filters.category);
    renderFilterTitle(state.filters.category);
    renderPresets(state.filters);
    renderPriceInputs(state.filters);
    renderSearchInputs(state.filters.q);
    renderPopular('heroPopular', state.filters.q);
    renderPopular('listPopular', state.filters.q);
    rerenderChips();
  } catch (err) {
    console.error('[init] 초기 렌더 실패 — 목록은 계속 진행합니다:', err);
  }

  wireEvents();

  // 목록과 meta는 병렬로 출발한다. 목록이 meta를 기다릴 이유가 없다.
  load();

  try {
    state.meta = await fetchMeta();
    renderCategoryCards(state.meta);
    rerenderChips();
    renderResultHeader(state);
    renderList(state); // 빈 화면 문구가 meta(수집 전 여부)에 걸려 있어 한 번 더
  } catch {
    // meta가 죽어도 목록은 산다. 칩 선택지와 카드 건수만 없는 채로 동작한다.
    renderCategoryCards(null);
  }

  try {
    me = await fetchMe();
    renderAccount();
  } catch {
    /* 로그인 상태를 못 읽어도 검색 화면은 그대로 쓴다 */
  }

  try {
    state.reco.items = await fetchReco(50);
    renderReco(state.reco);
  } catch {
    /* 레일 실패는 침묵 — 대문의 나머지는 성립한다 */
  }
}

init();
