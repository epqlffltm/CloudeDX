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

import { fetchListings, fetchLive, fetchMeta, fetchSeller } from './api.js';
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

// 브이월드 정적 지도. 브라우저가 직접 호출하므로 키가 프론트에 노출된다 —
// 원래 그런 용도로 발급하는 키이고, 인증키 신청 시 사용 도메인을 등록해 두면
// 남이 가져다 쓰는 것을 막을 수 있다.
//
// 키가 비어 있으면 이미지 요청이 실패하고, onerror가 지도 블록을 통째로 지운다.
// 그래서 키를 넣지 않아도 화면은 깨지지 않는다.

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
  // 실시간 조회 상태. idle | running | done
  // 화면에 "최신 매물을 확인하는 중" 배지를 띄우는 용도다.
  live: 'idle',
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

  // 입점 판매자 매물은 바깥 링크가 아니라 판매자 패널을 연다. 원문 사이트가
  // 없는 판매자라 나갈 곳이 없고, 연락처와 매장 위치가 우리 화면에만 있다.
  const tag = item.seller_id ? 'button' : 'a';
  const attrs = item.seller_id
    ? `type="button" data-seller="${item.seller_id}"`
    : `href="${esc(item.item_url)}" target="_blank" rel="noopener noreferrer"`;

  return `
    <${tag} class="p-card" ${attrs}>
      <div class="p-img${item.image_url ? '' : ' p-img--empty'}">
        ${image}
        <span class="p-badge">${esc(item.source)}</span>
        ${seal}
      </div>
      <div class="p-brand">${esc(toDisplayBrand(item.brand))}</div>
      <div class="p-name">${esc(item.title)}</div>
      <div class="p-price${unknown ? ' p-price--unknown' : ''}">${priceText(item.price)}</div>
    </${tag}>`;
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

  const badge = state.live === 'running'
    ? ' <span class="live-badge">최신 매물 확인 중…</span>'
    : '';

  $('resultCount').innerHTML = state.status === 'ready'
    ? `총 <strong>${won.format(state.total)}</strong>건${badge}`
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

/**
 * 검색어로 번개장터를 즉시 조회하고, 새 매물이 저장됐으면 목록을 다시 그린다.
 *
 * DB 조회를 막지 않는 것이 핵심이다. 화면은 이미 결과를 보여주고 있고, 이 함수는
 * 그 위에 몇 초 뒤 최신 매물을 얹는다. 그래서 await로 순서를 묶지 않고 따로 띄운다.
 *
 * 실패는 조용히 넘어간다. 사용자가 볼 목록은 멀쩡한데 "실시간 조회 실패"를 띄우면
 * 아무 문제 없는 화면에 오류만 얹는 셈이다.
 */
async function refreshLive(query) {
  if (!query) return;

  state.live = 'running';
  renderResultHeader();

  try {
    const result = await fetchLive(query);

    // 저장된 것이 있을 때만 다시 그린다. skipped/ignored/failed면 목록이 그대로다.
    if (result.status === 'saved' && result.saved > 0) {
      await loadList();
    }
  } catch {
    // 네트워크가 끊긴 경우. 목록은 이미 떠 있으므로 아무것도 하지 않는다.
  } finally {
    state.live = 'done';
    renderResultHeader();
  }
}

/**
 * 입점 판매자 패널.
 *
 * 지도는 브이월드 정적 지도 이미지를 브라우저가 직접 받는다. **백엔드를 거치지
 * 않는다** — 백엔드는 폐쇄망에 있고, 지도 타일은 사용자 브라우저가 외부망에서
 * 가져오면 되는 자원이라 서버가 중계할 이유가 없다.
 *
 * 매장이 없는 판매자는 지도를 아예 그리지 않는다. has_store가 false면 주소와
 * 좌표가 없는 것이 정상이고, 빈 지도를 띄우면 "위치를 못 찾았다"로 읽힌다.
 */
/**
 * 약도처럼 보이는 SVG를 그린다 — 실제 지도가 아니다.
 *
 * 시안의 지도 자리는 "그 동네 같은 분위기"가 목적이지 길찾기가 아니다. 진짜
 * 지도를 붙이면 API 키·외부망·타일 로딩이 전부 이 모달의 의존성이 되는데,
 * 약도라는 목적에는 과하다. 대신 판매자 id를 시드로 쓴 결정적 난수로 도로를
 * 배치한다 — 같은 판매자는 늘 같은 약도, 다른 판매자는 다른 약도가 나온다.
 */
function sketchMap(seed) {
  // mulberry32 — 시드 고정 난수. Math.random()이면 열 때마다 약도가 바뀐다.
  let s = (seed * 2654435761) >>> 0;
  const rng = () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const W = 640; const H = 300;
  const parts = [];
  const label = (x, y, text, size = 12, fill = '#6b655c', weight = 500, anchor = 'middle') =>
    `<text x="${x}" y="${y}" font-family="'Noto Sans KR',sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${text}</text>`;

  // ── 도로망 ──────────────────────────────────────────────
  // 처음 버전은 무작위 선만 흩었더니 "지도"로 읽히지 않았다. 약도가 약도로
  // 보이는 것은 선의 양이 아니라 **읽을 수 있는 표지** 덕분이다 — 그래서
  // 큰길 두 개의 교차 + 이름표 + 랜드마크라는 고정 문법 위에, 난수는
  // 위치를 조금씩 흔드는 데만 쓴다(판매자마다 다른 동네처럼 보이게).

  // 골목 — 옅게 몇 개만(질감용). 라벨을 덮지 않게 수를 줄였다.
  for (let i = 0; i < 3; i += 1) {
    const y = H * (0.1 + rng() * 0.8);
    parts.push(`<line x1="-10" y1="${y}" x2="${W + 10}" y2="${y + (rng() - 0.5) * 24}" stroke="#e3dccf" stroke-width="3"/>`);
  }
  for (let i = 0; i < 3; i += 1) {
    const x = W * (0.08 + rng() * 0.84);
    parts.push(`<line x1="${x}" y1="-10" x2="${x + (rng() - 0.5) * 24}" y2="${H + 10}" stroke="#e3dccf" stroke-width="3"/>`);
  }

  // 하천 — 오른쪽 가장자리를 지나는 곡선 (있어도 시선을 뺏지 않게 연하게)
  const rx = W * (0.86 + rng() * 0.1);
  parts.push(`<path d="M ${rx} -20 C ${rx - 30 + rng() * 60} ${H * 0.35}, ${rx + 30 - rng() * 60} ${H * 0.65}, ${rx - 20 + rng() * 40} ${H + 20}" stroke="#d3ddd8" stroke-width="22" fill="none" stroke-linecap="round"/>`);

  // 큰길(가로) — 흰 점선 중앙선을 넣어 도로임이 바로 읽히게
  const roadY = H * (0.71 + (rng() - 0.5) * 0.07);
  const roadTilt = (rng() - 0.5) * 24;
  parts.push(`<line x1="-10" y1="${roadY}" x2="${W + 10}" y2="${roadY + roadTilt}" stroke="#8e8880" stroke-width="16" stroke-linecap="round"/>`);
  parts.push(`<line x1="-10" y1="${roadY}" x2="${W + 10}" y2="${roadY + roadTilt}" stroke="#f6f3ec" stroke-width="2" stroke-dasharray="14 10"/>`);

  // 큰길(세로)
  const roadX = W * (0.34 + (rng() - 0.5) * 0.1);
  parts.push(`<line x1="${roadX}" y1="-10" x2="${roadX + (rng() - 0.5) * 24}" y2="${H + 10}" stroke="#9b958c" stroke-width="12" stroke-linecap="round"/>`);

  // 도로 이름 — 시연용 가상 지명. 실제 지명을 쓰면 "진짜 지도"로 오해된다.
  parts.push(label(W * 0.75, roadY - 12, '중앙대로', 12, '#7a736a', 600));
  parts.push(label(roadX + 14, H * 0.14, '시장길', 11, '#8a8378', 500, 'start'));

  // ── 랜드마크 ────────────────────────────────────────────
  // 지하철역 — 큰길 교차점 곁. 약도에서 가장 힘이 센 기준점이라 항상 넣는다.
  // 세로길 왼쪽·매장 구역 바깥에 둔다 — 중앙 상자와 겹치면 서로를 가린다.
  const stX = roadX - 36 - rng() * 8;
  const stY = roadY - 34 - rng() * 8;
  parts.push(`<circle cx="${stX}" cy="${stY}" r="13" fill="#fff" stroke="#4b5a6b" stroke-width="3.5"/>`);
  parts.push(label(stX, stY + 4.5, '역', 12, '#4b5a6b', 700));
  parts.push(label(stX, stY - 20, '3번 출구', 10.5, '#8a8378'));

  // 공원 — 왼쪽/오른쪽 위 중 난수로 한 곳
  const parkX = rng() < 0.5 ? W * 0.12 : W * 0.56;
  const parkY = H * (0.12 + rng() * 0.08);
  parts.push(`<rect x="${parkX}" y="${parkY}" width="92" height="54" rx="14" fill="#dde6d3" stroke="#b9c9ab" stroke-width="1.5"/>`);
  parts.push(label(parkX + 46, parkY + 32, '공원', 12, '#5d7050', 600));

  // 작은 건물 두 개 — 은행·카페. "매장 옆 무엇"이라고 말할 거리를 만든다.
  const bankX = W * (0.68 + rng() * 0.08);
  const bankY = roadY + 18 + rng() * 6;
  parts.push(`<rect x="${bankX}" y="${bankY}" width="56" height="34" rx="6" fill="#eae3d4" stroke="#c9c2b6" stroke-width="1.5"/>`);
  parts.push(label(bankX + 28, bankY + 22, '은행', 11.5, '#6b655c', 600));

  const cafeX = W * (0.14 + rng() * 0.06);
  const cafeY = roadY + 18 + rng() * 6;
  parts.push(`<rect x="${cafeX}" y="${cafeY}" width="50" height="32" rx="6" fill="#eae3d4" stroke="#c9c2b6" stroke-width="1.5"/>`);
  parts.push(label(cafeX + 25, cafeY + 21, '카페', 11.5, '#6b655c', 600));

  // ── 매장 구역 ───────────────────────────────────────────
  // 핀(.seller-pin 오버레이)이 정중앙에 오므로 그 아래 이름표를 깐다.
  parts.push(`<rect x="${W / 2 - 74}" y="${H / 2 - 50}" width="148" height="100" rx="14" fill="rgba(255,255,255,.55)" stroke="#b7ae9e" stroke-width="2"/>`);
  parts.push(label(W / 2, H / 2 + 40, '매장', 13.5, '#3a352e', 700));

  // 나침반 — 오른쪽 위. 이게 있으면 "지도"라는 신호가 한 번 더 간다.
  parts.push(`<g transform="translate(${W - 44}, 40)"><circle r="15" fill="#fff" stroke="#c9c2b6" stroke-width="1.5"/><path d="M 0 -9 L 4 5 L 0 2 L -4 5 Z" fill="#3a352e"/><text y="-20" font-family="sans-serif" font-size="11" font-weight="700" fill="#6b655c" text-anchor="middle">N</text></g>`);

  return `<svg class="seller-sketch" viewBox="0 0 ${W} ${H}" role="img" aria-label="매장 위치 약도" preserveAspectRatio="xMidYMid slice"><rect width="${W}" height="${H}" fill="#f2efe9"/>${parts.join('')}</svg>`;
}

function renderSellerPanel(seller, goods) {
  const panel = $('sellerPanel');

  const hasMap = seller.has_store && seller.latitude && seller.longitude;
  const all = goods ?? [];

  // 시안의 우측 매장 사진 자리 — 판매자의 매장 사진(간판·가게 내부)이다.
  // 매물 사진을 대신 세우지 않는다: 가게 소개 칸에 파는 물건이 걸리면 이상하다.
  // 사진이 없으면(온라인 전용 판매자 등) 칸을 그리지 않고 정보가 전체 폭을 쓰고,
  // 경로는 있는데 파일이 빠진 경우에도 onerror가 같은 레이아웃으로 되돌린다.
  const photo = seller.photo_url
    ? `<div class="seller-photo"><img src="${esc(seller.photo_url)}" alt="${esc(seller.name)} 매장 사진" loading="lazy"
         onerror="this.closest('.seller-grid').classList.add('seller-grid--solo'); this.closest('.seller-photo').remove()"></div>`
    : '';

  const store = seller.has_store
    ? `<div class="sf"><dt>주소</dt><dd>${esc(seller.address ?? '등록되지 않음')}</dd></div>`
    : '<div class="sf"><dt>매장</dt><dd>매장 없이 온라인으로만 판매합니다.</dd></div>';

  // 대표 제품 — 이 판매자가 등록한 실제 매물, 최대 4개.
  const products = all.slice(0, 4);
  const cards = products.map((g) => `
      <figure class="sg-card">
        ${g.image_url
          ? `<img src="${esc(g.image_url)}" alt="" loading="lazy">`
          : `<div class="sg-noimg" aria-hidden="true">${esc(toDisplayBrand(g.brand))}</div>`}
        <figcaption>
          <span class="sg-title">${esc(g.title)}</span>
          <span class="sg-price">${priceText(g.price)}</span>
        </figcaption>
      </figure>`).join('');

  const goodsSection = cards
    ? `
      <section class="seller-goods" aria-label="대표 제품">
        <h3 class="seller-h">대표 제품</h3>
        <div class="sg-grid">${cards}</div>
      </section>`
    : '';

  // 시안의 "찾아오시는 길" — 약도 + 주소 + VIEW DIRECTIONS.
  // 지도는 정확한 지도가 아니라 **약도처럼 보이는 생성 그림**이다(아래 sketchMap).
  // 외부 지도 API가 필요 없고, 정확한 위치가 필요한 사람은 View Directions로
  // 실제 지도(카카오맵)에 간다. 좌표가 없으면 링크만 빠진다.
  const directions = seller.has_store
    ? `
      <section class="seller-way" aria-label="찾아오시는 길">
        <h3 class="seller-h">찾아오시는 길</h3>
        <div class="seller-map">
          ${sketchMap(seller.id)}
          <span class="seller-pin" aria-hidden="true"></span>
        </div>
        <div class="seller-map-foot">
          <span class="seller-map-addr">${esc(seller.address ?? '')}</span>
          ${seller.latitude && seller.longitude
            ? `<a class="seller-map-link" target="_blank" rel="noopener"
                 href="https://map.kakao.com/link/map/${encodeURIComponent(seller.name)},${seller.latitude},${seller.longitude}">View Directions</a>`
            : ''}
        </div>
        <p class="seller-map-note">위치를 표현한 약도입니다 — 실제 지형·축척과 다릅니다.</p>
      </section>`
    : '';

  panel.innerHTML = `
    <div class="seller-sheet" role="dialog" aria-modal="true" aria-labelledby="sellerName">
      <button class="seller-close" type="button" data-seller-close aria-label="닫기">&times;</button>

      <header class="seller-head">
        <p class="seller-eyebrow">입점 판매자 정보</p>
        <h2 class="seller-name" id="sellerName">${esc(seller.name)}</h2>
        ${seller.description ? `<p class="seller-desc">“${esc(seller.description)}”</p>` : ''}
      </header>

      <div class="seller-body">
        <div class="seller-grid${photo ? '' : ' seller-grid--solo'}">
          <dl class="seller-facts">
            <div class="sf"><dt>사업자 등록번호</dt><dd>${esc(seller.business_number)}</dd></div>
            <div class="sf"><dt>연락처</dt><dd><a href="tel:${esc(seller.phone)}">${esc(seller.phone)}</a></dd></div>
            ${store}
            <div class="sf"><dt>등록 매물</dt><dd>${won.format(seller.item_count)}건</dd></div>
          </dl>
          ${photo}
        </div>

        ${goodsSection}
        ${directions}

        <p class="seller-disclaimer">
          사업자등록번호는 형식만 확인한 값입니다. 국세청 진위확인을 거치지 않았으며,
          거래 전 직접 확인하시기 바랍니다.
        </p>
      </div>

      <footer class="seller-foot">
        <a class="seller-cta" href="tel:${esc(seller.phone)}">연락하기 (Contact Seller)</a>
      </footer>
    </div>`;

  panel.hidden = false;
  panel.querySelector('[data-seller-close]')?.focus();
}

function closeSellerPanel() {
  const panel = $('sellerPanel');
  panel.hidden = true;
  panel.innerHTML = '';
}

/**
 * 판매자의 매물을 "대표 제품"과 사진 칸에 쓸 재료로 가져온다.
 *
 * 전용 API 없이 목록 API를 재사용한다 — ListingOut에 seller_id가 이미 실려
 * 있어서, 직접등록 매물을 받아 이 판매자 것만 고르면 된다. 시연 규모에서
 * 직접등록은 수십 건이라 첫 페이지로 충분하다. 사진 있는 매물을 앞세운다.
 */
async function fetchSellerGoods(sellerId) {
  try {
    const page = await fetchListings(
      { category: 'all', sort: 'latest', source: '직접등록' }, 0, 60,
    );
    // dataset에서 온 id는 문자열이라 숫자로 맞춘다.
    const mine = page.items.filter((it) => it.seller_id === Number(sellerId));

    return [...mine.filter((it) => it.image_url), ...mine.filter((it) => !it.image_url)];
  } catch {
    return null; // 실패는 절 생략으로 — 판매자 정보 자체를 가릴 이유가 없다.
  }
}

async function openSeller(sellerId) {
  const panel = $('sellerPanel');

  panel.hidden = false;
  panel.innerHTML = '<div class="seller-sheet"><p class="seller-loading">판매자 정보를 불러오는 중…</p></div>';

  try {
    const [seller, goods] = await Promise.all([
      fetchSeller(sellerId),
      fetchSellerGoods(sellerId),
    ]);
    renderSellerPanel(seller, goods);
  } catch {
    panel.innerHTML = `
      <div class="seller-sheet">
        <button class="seller-close" type="button" data-seller-close aria-label="닫기">&times;</button>
        <p class="seller-loading">판매자 정보를 불러오지 못했습니다.</p>
      </div>`;
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

  // 검색어가 있을 때만 실시간 조회를 건다. 브랜드 칩이나 카테고리 클릭은 이미
  // 수집된 범위를 좁히는 동작이라 새로 긁을 이유가 없다.
  if (patch.q !== undefined && state.filters.q) {
    refreshLive(state.filters.q);
  }

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

  const sellerBtn = hit('[data-seller]');
  if (sellerBtn) { openSeller(sellerBtn.dataset.seller); return; }

  // 닫기 버튼, 또는 시트 바깥(배경)을 눌렀을 때.
  if (hit('[data-seller-close]') || e.target.id === 'sellerPanel') {
    closeSellerPanel();
    return;
  }

  const tab = hit('[data-rail]');
  if (tab) {
    state.railTab = tab.dataset.rail;

    document.querySelectorAll('[data-rail]').forEach((b) => {
      b.setAttribute('aria-selected', String(b === tab));
    });

    loadRail();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('sellerPanel').hidden) closeSellerPanel();
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
