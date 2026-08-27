// web/js/home.js
//
// 대문 + 검색 결과 화면의 컨트롤러.
//
// 데이터 접근은 api.js가 전담한다 — 이 파일에 fetch는 없다. 계약(ListingOut)이
// 바뀌면 api.js와 여기 cardHtml만 보면 된다.
//
// **카테고리 목록을 하드코딩하지 않는다.** /api/meta의 categories(카테고리별 건수)를
// 그대로 그린다. app/domain/search_plan.py에 카테고리를 추가하면 크롤이 한 바퀴 돈
// 뒤 이 화면에 자동으로 칸이 늘어난다. 프론트에 목록을 박아두면 백엔드를 고칠 때마다
// 양쪽을 같이 고쳐야 하고, 실제로는 한쪽만 고쳐서 어긋난다.

import { fetchListings, fetchMeta } from './api.js';
import { PAGE_SIZE, PRICE_UNLIMITED, toDisplayBrand } from './state.js';

// ── 표시용 사전 ─────────────────────────────────────────────────────
//
// 백엔드가 내려주는 카테고리 키의 한국어 이름과 아이콘. 사전에 없는 키가 와도
// 화면에서 사라지지 않게, 키 자체를 이름으로 쓰고 기본 아이콘을 붙인다.
// 이름이 없다고 매물을 감추면 "DB에는 있는데 화면에 없는" 상태가 된다.

const CATEGORY_LABELS = {
  bag: '가방',
  watch: '시계',
  jewelry: '주얼리',
  apparel: '의류',
  shoes: '신발',
  accessory: '액세서리',
  living: '리빙',
};

const CATEGORY_ICONS = {
  bag: 'i-bag',
  watch: 'i-watch',
  jewelry: 'i-gem',
  apparel: 'i-shirt',
  shoes: 'i-shoe',
  accessory: 'i-ring',
  living: 'i-home',
};

const SORT_OPTIONS = [
  { value: 'latest', label: '최신순' },
  { value: 'price_asc', label: '최저가순' },
  { value: 'price_desc', label: '최고가순' },
];

const ALL = '전체';

const categoryLabel = (id) => CATEGORY_LABELS[id] ?? id;
const categoryIcon = (id) => CATEGORY_ICONS[id] ?? 'i-sparkles';

// ── 상태 ────────────────────────────────────────────────────────────

const state = {
  mode: 'home', // 'home' | 'list'
  filters: {
    category: 'all',
    brand: ALL,
    source: ALL,
    q: '',
    min: 0,
    max: PRICE_UNLIMITED,
    sort: 'latest',
  },
  meta: null,
  items: [],
  total: 0,
  offset: 0,
  hasNext: false,
  status: 'loading', // loading | ready | error
  errorMessage: '',
  // 대문 레일 탭. 'latest'는 최신순 전체, 'authenticated'는 인증 매물만.
  railTab: 'latest',
};

// 이전 요청을 취소한다. 필터를 빠르게 바꾸면 응답이 순서를 바꿔 도착해서,
// 늦게 온 예전 응답이 최신 결과를 덮어쓴다.
let listController = null;

const $ = (id) => document.getElementById(id);

// ── 공용 포맷 ───────────────────────────────────────────────────────

const won = new Intl.NumberFormat('ko-KR');

function priceText(value) {
  return value === null || value === undefined ? '가격 미상' : `${won.format(value)}원`;
}

/**
 * HTML 이스케이프.
 *
 * 제목은 셀러가 쓴 문자열이고 innerHTML로 들어간다. 정제를 거쳐도 <, >, & 는
 * 남을 수 있으므로 반드시 통과시킨다.
 */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ── 렌더 ────────────────────────────────────────────────────────────

/**
 * 매물 카드 하나.
 *
 * 거래는 원문 사이트에서 이뤄지므로 카드 전체가 바깥 링크다. 새 탭으로 여는 것은
 * 사용자가 비교하던 목록을 잃지 않게 하려는 것이고, rel=noopener는 새 탭이
 * window.opener로 이 페이지를 조작하지 못하게 막는다.
 *
 * referrerpolicy는 이미지에 붙인다. 수집처 CDN 중에 Referer를 보고 외부 표시를
 * 막는 곳이 있어서, 레퍼러를 빼면 그대로 뜨는 경우가 있다. 근본 해결은 아니다 —
 * 수집 시점에 이미지를 우리 쪽에 저장하는 것이 정답이고, 그때까지의 임시 방편이다.
 *
 * 정품인증 씰은 is_authenticated가 true일 때만 그린다. 이 값은 기업고객이 증표를
 * 확인해 등록한 매물에만 붙고, 크롤링분은 예외 없이 false다. 프론트에서 다른 조건
 * (수집처가 '직접등록'인지 등)으로 대신 판정하지 않는다 — 판정 규칙이 두 곳으로
 * 갈라지면 백엔드를 고쳤을 때 화면만 예전 규칙으로 남는다.
 */
function cardHtml(item) {
  const image = item.image_url
    ? `<img src="${esc(item.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : '<span>이미지 없음</span>';

  const unknown = item.price === null || item.price === undefined;

  const seal = item.is_authenticated
    ? '<span class="p-seal"><svg viewBox="0 0 24 24"><use href="#i-seal"/></svg>정품인증</span>'
    : '';

  return `
    <a class="p-card" href="${esc(item.item_url)}" target="_blank" rel="noopener noreferrer">
      <div class="p-img${item.image_url ? '' : ' p-img--empty'}">
        ${image}
        <span class="p-badge">${esc(item.source)}</span>
        ${seal}
      </div>
      <div class="p-brand">${esc(toDisplayBrand(item.brand))}</div>
      <div class="p-name">${esc(item.title)}</div>
      <div class="p-price${unknown ? ' p-price--unknown' : ''}">${priceText(item.price)}</div>
    </a>`;
}

function skeletonHtml(count) {
  return Array.from({ length: count }, () => `
    <div class="p-card skeleton" aria-hidden="true">
      <div class="p-img"></div>
      <div class="p-brand">&nbsp;</div>
      <div class="p-name">&nbsp;</div>
      <div class="p-price">&nbsp;</div>
    </div>`).join('');
}

function stateHtml({ title, body, retry = false, error = false }) {
  return `
    <div class="state${error ? ' state--error' : ''}">
      <strong>${esc(title)}</strong>
      <span>${esc(body)}</span>
      ${retry ? '<div><button type="button" data-retry>다시 시도</button></div>' : ''}
    </div>`;
}

function renderNav() {
  const nav = $('mainNav');
  const cats = Object.keys(state.meta?.categories ?? {});

  nav.innerHTML = [
    `<button type="button" data-category="all"
       aria-current="${state.mode === 'list' && state.filters.category === 'all'}">전체 매물</button>`,
    ...cats.map((id) => `
      <button type="button" data-category="${esc(id)}"
        aria-current="${state.mode === 'list' && state.filters.category === id}">${esc(categoryLabel(id))}</button>`),
  ].join('');
}

function renderCategories() {
  const entries = Object.entries(state.meta?.categories ?? {});
  const grid = $('catGrid');

  if (entries.length === 0) {
    grid.innerHTML = stateHtml({
      title: '아직 수집된 매물이 없습니다',
      body: '첫 수집이 끝나면 카테고리가 여기에 나타납니다.',
    });
    return;
  }

  grid.innerHTML = entries.map(([id, count]) => `
    <button class="cat-item" type="button" data-category="${esc(id)}">
      <span class="cat-circle"><svg viewBox="0 0 24 24"><use href="#${categoryIcon(id)}"/></svg></span>
      <span class="cat-label">${esc(categoryLabel(id))}</span>
      <span class="cat-count">${won.format(count)}건</span>
    </button>`).join('');
}

function renderBrands() {
  const brands = state.meta?.brands ?? [];

  $('brandScroll').innerHTML = brands.map((ko) => {
    const display = toDisplayBrand(ko);

    return `
      <button class="brand-item" type="button" data-brand="${esc(ko)}">
        <span class="brand-monogram">${esc(display.slice(0, 2))}</span>
        <span class="brand-name">${esc(display)}</span>
      </button>`;
  }).join('');
}

function renderFilterChips() {
  const sources = [ALL, ...(state.meta?.sources ?? [])];

  $('sourceChips').innerHTML = [
    '<span class="filter-label">수집처</span>',
    ...sources.map((s) => `
      <button class="chip" type="button" data-source="${esc(s)}"
        aria-pressed="${state.filters.source === s}">${esc(s)}</button>`),
  ].join('');

  // 브랜드는 현재 카테고리에서 실제로 수집하는 것만 보여준다. 전체 목록을 늘
  // 뿌리면 시계 화면에 고야드가 뜨고, 눌러도 0건이다.
  const byCategory = state.meta?.brands_by_category ?? {};
  const pool = state.filters.category === 'all'
    ? (state.meta?.brands ?? [])
    : (byCategory[state.filters.category] ?? state.meta?.brands ?? []);

  $('brandChips').innerHTML = [
    '<span class="filter-label">브랜드</span>',
    ...[ALL, ...pool].map((b) => `
      <button class="chip" type="button" data-brand="${esc(b)}"
        aria-pressed="${state.filters.brand === b}">${esc(b === ALL ? b : toDisplayBrand(b))}</button>`),
  ].join('');

  $('sortSelect').innerHTML = SORT_OPTIONS.map((o) => `
    <option value="${o.value}"${state.filters.sort === o.value ? ' selected' : ''}>${o.label}</option>`).join('');
}

function renderResultHeader() {
  const { category, brand, q } = state.filters;

  const parts = [];
  if (brand !== ALL) parts.push(toDisplayBrand(brand));
  if (category !== 'all') parts.push(categoryLabel(category));

  $('resultTitle').textContent = q
    ? `"${q}" 검색 결과`
    : (parts.join(' ') || '전체 매물');

  $('resultCount').innerHTML = state.status === 'ready'
    ? `총 <strong>${won.format(state.total)}</strong>건`
    : '';
}

function renderList() {
  const grid = $('resultGrid');
  const pager = $('pager');

  if (state.status === 'loading') {
    grid.innerHTML = skeletonHtml(10);
    pager.innerHTML = '';
    return;
  }

  if (state.status === 'error') {
    grid.innerHTML = stateHtml({
      title: '매물을 불러오지 못했습니다',
      body: state.errorMessage,
      retry: true,
      error: true,
    });
    pager.innerHTML = '';
    return;
  }

  if (state.items.length === 0) {
    grid.innerHTML = stateHtml({
      title: '조건에 맞는 매물이 없습니다',
      body: '브랜드나 수집처 조건을 줄여서 다시 찾아보세요.',
    });
    pager.innerHTML = '';
    return;
  }

  grid.innerHTML = state.items.map(cardHtml).join('');

  const page = Math.floor(state.offset / PAGE_SIZE) + 1;
  const pages = Math.max(Math.ceil(state.total / PAGE_SIZE), 1);

  pager.innerHTML = `
    <button type="button" data-page="prev"${state.offset === 0 ? ' disabled' : ''}>이전</button>
    <span class="pager-status">${page} / ${pages}</span>
    <button type="button" data-page="next"${state.hasNext ? '' : ' disabled'}>다음</button>`;
}

function renderRail(items) {
  const empty = state.railTab === 'authenticated'
    ? { title: '인증 매물이 아직 없습니다', body: '기업고객이 증표를 확인해 등록한 매물이 여기에 모입니다.' }
    : { title: '표시할 매물이 없습니다', body: '수집이 끝나면 이곳에 나타납니다.' };

  $('railGrid').innerHTML = items.length === 0
    ? stateHtml(empty)
    : items.map(cardHtml).join('');
}

/**
 * 대문 히어로 배경.
 *
 * 시안은 picsum 플레이스홀더를 썼는데, 실서비스에 랜덤 사진을 둘 수는 없다.
 * 가장 최근 매물의 사진을 쓴다 — 화면이 "지금 뭐가 올라와 있나"를 그대로 보여준다.
 * 사진이 없으면 배경색만 남기고 넘어간다.
 */
function renderHero(items) {
  const withImage = items.find((it) => it.image_url);
  if (!withImage) return;

  const hero = $('hero');
  const img = document.createElement('img');

  img.src = withImage.image_url;
  img.alt = '';
  img.referrerPolicy = 'no-referrer';
  hero.prepend(img);
}

// ── 주소창 ──────────────────────────────────────────────────────────

function writeURL() {
  const f = state.filters;
  const q = new URLSearchParams();

  if (state.mode === 'list') q.set('view', 'list');
  if (f.category !== 'all') q.set('cat', f.category);
  if (f.brand !== ALL) q.set('brand', f.brand);
  if (f.source !== ALL) q.set('source', f.source);
  if (f.q) q.set('q', f.q);
  if (f.sort !== 'latest') q.set('sort', f.sort);
  if (state.offset > 0) q.set('offset', String(state.offset));

  const qs = q.toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function readURL() {
  const p = new URLSearchParams(location.search);
  const offset = Number(p.get('offset'));
  const sort = p.get('sort');

  state.mode = p.get('view') === 'list' ? 'list' : 'home';
  state.offset = Number.isFinite(offset) && offset > 0 ? offset : 0;

  Object.assign(state.filters, {
    // 카테고리는 검증하지 않는다. 유효한 값의 목록은 백엔드가 알고 있고,
    // 프론트가 그걸 복제하면 카테고리를 추가할 때마다 여기도 고쳐야 한다.
    // 없는 카테고리를 넣으면 서버가 0건을 돌려주고 화면은 빈 상태를 그린다.
    category: p.get('cat') || 'all',
    brand: p.get('brand') || ALL,
    source: p.get('source') || ALL,
    q: p.get('q') || '',
    sort: SORT_OPTIONS.some((o) => o.value === sort) ? sort : 'latest',
  });
}

// ── 데이터 ──────────────────────────────────────────────────────────

async function loadList() {
  listController?.abort();
  listController = new AbortController();

  state.status = 'loading';
  renderResultHeader();
  renderList();

  try {
    const data = await fetchListings(
      state.filters, state.offset, PAGE_SIZE, listController.signal,
    );

    state.items = data.items;
    state.total = data.total;
    state.hasNext = data.has_next;
    state.status = 'ready';
  } catch (err) {
    if (err.name === 'AbortError') return;

    state.status = 'error';
    state.errorMessage = err.message || '알 수 없는 오류입니다.';
  }

  renderResultHeader();
  renderList();
  renderFilterChips();
}

async function loadRail() {
  try {
    const data = await fetchListings(
      {
        ...state.filters,
        category: 'all', brand: ALL, source: ALL, q: '', sort: 'latest',
        authenticatedOnly: state.railTab === 'authenticated',
      },
      0, 12,
    );

    renderRail(data.items);
    renderHero(data.items);
  } catch {
    // 대문 레일은 부가 정보다. 실패해도 화면 전체를 막지 않는다.
    renderRail([]);
  }
}

async function loadMeta() {
  try {
    state.meta = await fetchMeta();
  } catch {
    state.meta = null;
  }

  renderNav();
  renderCategories();
  renderBrands();
  renderFilterChips();

  const at = state.meta?.last_crawled_at;
  $('lastCrawled').textContent = at
    ? `마지막 수집 ${new Date(at).toLocaleString('ko-KR')}`
    : '';
}

// ── 화면 전환 ───────────────────────────────────────────────────────

function apply(patch, { resetOffset = true } = {}) {
  Object.assign(state.filters, patch);
  if (resetOffset) state.offset = 0;

  state.mode = 'list';
  document.body.className = 'mode-list';

  writeURL();
  renderNav();
  renderFilterChips();
  loadList();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function goHome() {
  state.mode = 'home';
  document.body.className = 'mode-home';

  Object.assign(state.filters, {
    category: 'all', brand: ALL, source: ALL, q: '', sort: 'latest',
  });
  state.offset = 0;

  $('searchInput').value = '';
  writeURL();
  renderNav();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── 이벤트 ──────────────────────────────────────────────────────────
//
// 개별 요소에 리스너를 달지 않고 document에서 한 번 받는다. 카드·칩·카테고리는
// 렌더할 때마다 새로 만들어지므로, 요소마다 붙이면 다시 그릴 때마다 다시 붙여야
// 하고 하나라도 빠지면 조용히 안 눌린다.

document.addEventListener('click', (e) => {
  const hit = (sel) => e.target.closest(sel);

  if (hit('[data-home]')) { goHome(); return; }

  if (hit('[data-browse]')) {
    e.preventDefault();
    apply({ category: 'all', brand: ALL, source: ALL, q: '' });
    return;
  }

  const cat = hit('[data-category]');
  if (cat) { apply({ category: cat.dataset.category, brand: ALL }); return; }

  const brand = hit('[data-brand]');
  if (brand) { apply({ brand: brand.dataset.brand }); return; }

  const source = hit('[data-source]');
  if (source) { apply({ source: source.dataset.source }); return; }

  const page = hit('[data-page]');
  if (page && !page.disabled) {
    state.offset = page.dataset.page === 'next'
      ? state.offset + PAGE_SIZE
      : Math.max(state.offset - PAGE_SIZE, 0);

    writeURL();
    loadList();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }

  if (hit('[data-retry]')) { loadList(); return; }

  const tab = hit('[data-rail]');
  if (tab) {
    state.railTab = tab.dataset.rail;

    document.querySelectorAll('[data-rail]').forEach((b) => {
      b.setAttribute('aria-selected', String(b === tab));
    });

    loadRail();
  }
});

$('searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  apply({ q: $('searchInput').value.trim() });
});

$('sortSelect').addEventListener('change', (e) => {
  apply({ sort: e.target.value });
});

// ── 부팅 ────────────────────────────────────────────────────────────

readURL();
document.body.className = `mode-${state.mode}`;
$('searchInput').value = state.filters.q;

loadMeta();
loadRail();

if (state.mode === 'list') {
  renderResultHeader();
  loadList();
}
