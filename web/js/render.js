// web/js/render.js
//
// 상태(state.js)를 받아 화면을 그린다. 여기 함수들은 상태를 바꾸지 않는다 —
// 읽고 그리기만 한다. 목록은 조각 수정 없이 통째로 재생성한다.
// 한 페이지 30장 규모에서 innerHTML 재생성은 밀리초 단위라 diff 없이도 충분하다.

import {
  CATEGORY_CARDS,
  CATEGORY_TABS,
  PRICE_CAP,
  PRICE_PRESETS,
  PRICE_UNLIMITED,
  POPULAR_TERMS,
  SORT_OPTIONS,
  toDisplayBrand,
} from './state.js';

const el = (id) => document.getElementById(id);

/**
 * 수집 사이트의 제목이 그대로 들어오므로 이스케이프는 선택이 아니다.
 * React가 자동으로 해주던 일을 여기서는 손으로 한다 — 크롤링 데이터에
 * <script>가 섞여 들어오는 순간을 막는 유일한 방어선이다.
 */
export function escapeHtml(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const won = (n) => `${Number(n).toLocaleString('ko-KR')}원`;
const icon = (id, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24"><use href="#${id}"/></svg>`;

/* ------------------------------------------------------------------ 대문 */

/** 인기 검색어 칩. 대문과 결과 화면 두 곳에 같은 목록을 그린다. */
export function renderPopular(containerId, activeQuery) {
  const box = el(containerId);
  if (!box) return;

  box.innerHTML =
    `<span class="popular__label">추천:</span>` +
    POPULAR_TERMS.map(
      (t) => `<button type="button" class="${t === activeQuery ? 'on' : ''}" data-kw="${escapeHtml(t)}">${escapeHtml(t)}</button>`,
    ).join('');
}

/** 대문 카테고리 카드. 건수는 /api/meta가 오기 전엔 말줄임으로 둔다. */
export function renderCategoryCards(meta) {
  const box = el('catGrid');
  if (!box) return;

  box.innerHTML = CATEGORY_CARDS.map((c) => {
    const n = meta?.categories?.[c.id];
    const count = n == null ? '…' : `${n.toLocaleString('ko-KR')}개 매물`;

    return `
      <button class="cat" type="button" data-category="${c.id}">
        <span class="cat__body">
          <span class="cat__icon ${c.ready ? '' : 'cat__icon--muted'}">${icon(c.icon)}</span>
          <span>
            <span class="cat__title">${c.title}</span>
            ${c.ready ? '' : '<span class="cat__soon">준비중</span>'}
            <span class="cat__sub">${c.sub}</span>
          </span>
        </span>
        <span class="cat__foot">${count}</span>
      </button>`;
  }).join('');
}

/* -------------------------------------------------------------- 카테고리 탭 */

export function renderTabs(activeCategory) {
  const box = el('catTabs');
  if (!box) return;

  box.innerHTML = CATEGORY_TABS.map(
    (t) => `
      <button class="tab ${t.id === activeCategory ? 'on' : ''}" type="button" data-category="${t.id}">
        ${icon(t.icon)}<span>${escapeHtml(t.name)}</span>
      </button>`,
  ).join('');
}

/* ------------------------------------------------------------- 필터 패널 */

/**
 * 칩 한 벌. 브랜드·플랫폼은 문자열 목록에 '전체'를 앞세우고,
 * 정렬은 {value,label} 쌍을 그대로 쓴다.
 */
export function renderChips(containerId, values, active, { withAll = false } = {}) {
  const box = el(containerId);
  if (!box) return;

  const items = (withAll ? ['전체', ...values] : values).map((v) =>
    typeof v === 'string' ? { value: v, label: v } : v,
  );

  box.innerHTML = items
    .map(
      (it) => `
      <button type="button" class="chip ${it.value === active ? 'on' : ''}"
              data-chip="${containerId}" data-value="${escapeHtml(it.value)}">${escapeHtml(it.label)}</button>`,
    )
    .join('');
}

/**
 * 필터 패널 제목. 카테고리를 고르면 "시계 상세 필터 검색"처럼 바뀌고
 * 옆에 카테고리 배지가 붙는다.
 */
export function renderFilterTitle(category) {
  const title = el('filterTitle');
  const badge = el('filterCatBadge');
  if (!title || !badge) return;

  const names = { bag: '가방', watch: '시계', jewelry: '주얼리', apparel: '의류', shoes: '신발' };

  title.textContent = names[category] ? `${names[category]} 상세 필터 검색` : '상세 필터 검색';

  if (category === 'all') {
    badge.hidden = true;
  } else {
    badge.hidden = false;
    badge.textContent = CATEGORY_TABS.find((t) => t.id === category)?.name ?? '';
  }

  // 전체 카테고리에서는 브랜드 줄을 숨긴다 — 다섯 카테고리 브랜드를 전부
  // 늘어놓으면 칩이 40개가 넘어가 필터가 아니라 소음이 된다.
  const brandRow = el('brandRow');
  if (brandRow) brandRow.hidden = category === 'all';
}

export function renderPresets(filters) {
  const box = el('pricePresets');
  if (!box) return;

  box.innerHTML = PRICE_PRESETS.map(
    (p, i) => `
      <button type="button" class="preset ${filters.min === p.min && filters.max === p.max ? 'on' : ''}"
              data-preset="${i}">${escapeHtml(p.label)}</button>`,
  ).join('');
}

/** 가격 입력칸과 슬라이더를 현재 필터값으로 되돌려 그린다. */
export function renderPriceInputs(filters) {
  const min = el('minPrice');
  const max = el('maxPrice');
  const lo = el('rangeMin');
  const hi = el('rangeMax');
  const fill = el('rangeFill');

  if (min) min.value = filters.min > 0 ? Math.floor(filters.min / 10_000) : '';
  if (max) max.value = filters.max < PRICE_UNLIMITED ? Math.floor(filters.max / 10_000) : '';

  const loVal = Math.min(filters.min, PRICE_CAP);
  const hiVal = Math.min(filters.max, PRICE_CAP);

  if (lo) lo.value = String(loVal);
  if (hi) hi.value = String(hiVal);

  if (fill) {
    fill.style.left = `${(loVal / PRICE_CAP) * 100}%`;
    fill.style.right = `${100 - (hiVal / PRICE_CAP) * 100}%`;
  }
}

/** 검색창 두 개(대문·결과)가 같은 상태를 비춘다. */
export function renderSearchInputs(query) {
  for (const id of ['searchInput', 'heroSearchInput']) {
    const input = el(id);
    if (!input) continue;

    input.value = query;
    input.closest('.search')?.classList.toggle('has-value', Boolean(query));
  }
}

/* --------------------------------------------------- 결과 헤더 + 가격 통계 */

export function renderResultHeader(state) {
  const title = el('resultTitle');
  const sources = el('resultSources');

  if (sources) {
    const list = state.meta?.sources ?? [];
    sources.textContent = list.length ? list.join(' · ') : '';
  }

  if (!title) return;

  const q = state.filters.q;
  const head = q
    ? `<span class="q">'${escapeHtml(q)}'</span> 검색 결과`
    : '전체 등록 매물';

  title.innerHTML =
    `${head}<span class="count">총 <strong>${state.total.toLocaleString('ko-KR')}</strong>개 매물</span>`;
}

/**
 * 최저·평균·최고 시세.
 *
 * 지금 화면에 올라온 페이지가 아니라 받아온 전체 항목을 기준으로 낸다.
 * 가격 미상(null)은 계산에서 뺀다 — 0원으로 치면 최저가가 항상 0이 된다.
 */
export function renderPriceStats(items) {
  const box = el('priceStats');
  if (!box) return;

  const prices = items.map((i) => i.price).filter((p) => typeof p === 'number' && p > 0);

  if (prices.length === 0) {
    box.hidden = true;
    return;
  }

  const sum = prices.reduce((a, b) => a + b, 0);

  el('statMin').textContent = won(Math.min(...prices));
  el('statAvg').textContent = won(Math.round(sum / prices.length));
  el('statMax').textContent = won(Math.max(...prices));
  box.hidden = false;
}

/* ---------------------------------------------------------------- 매물 카드 */

/**
 * 카드 한 장. 전체가 원문으로 가는 진짜 <a>다 — div+onClick이 아니라 링크라서
 * 길게 눌러 미리보기·새 탭 열기가 공짜로 따라온다. 거래는 원문에서 이루어지는
 * 서비스라 카드의 유일한 행동이 "원문으로 간다"인 게 맞다.
 */
export function cardHtml(item) {
  const thumb = item.image_url
    ? `<img src="${escapeHtml(item.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
    : `<span class="noimg">이미지 없음</span>`;

  const price =
    item.price == null
      ? `<span class="card__price unknown">가격 미상</span>`
      : `<span class="card__price">${Number(item.price).toLocaleString('ko-KR')}<span class="won">원</span></span>`;

  return `
  <a class="card" href="${escapeHtml(item.item_url)}" target="_blank" rel="noopener noreferrer">
    <span class="card__thumb">
      ${thumb}
      <span class="tag-brand">${escapeHtml(toDisplayBrand(item.brand))}</span>
      <span class="tag-source">${escapeHtml(item.source)}</span>
    </span>
    <span class="card__body">
      <h3 class="card__title">${escapeHtml(item.title)}</h3>
      <span class="card__price-wrap">
        <span class="card__price-label">판매가</span>
        ${price}
      </span>
    </span>
  </a>`;
}

const SKELETON = `<div class="skel" aria-hidden="true"></div>`;

/** 목록 영역 전체를 상태에서 다시 그린다. 여기가 이 화면의 심장이다. */
export function renderList(state) {
  const grid = el('grid');
  if (!grid) return;

  if (state.status === 'loading') {
    grid.innerHTML = SKELETON.repeat(10);
    renderPager(state);
    return;
  }

  if (state.status === 'error') {
    grid.innerHTML = `
      <div class="empty">
        <div class="empty__icon">${icon('i-search')}</div>
        <h3>매물을 불러오지 못했습니다</h3>
        <p>${escapeHtml(state.errorMessage)}</p>
        <button type="button" class="btn-dark" data-action="retry">다시 시도</button>
      </div>`;
    renderPager(state);
    return;
  }

  if (state.items.length === 0) {
    // 빈 화면 두 가지를 구분한다: 아직 수집 전 vs 필터가 다 걸러냄.
    // 사용자가 할 일이 다르다 — 전자는 기다리기, 후자는 필터 풀기.
    const stock =
      state.filters.category === 'all'
        ? state.meta?.total_items
        : state.meta?.categories?.[state.filters.category];

    grid.innerHTML =
      (stock ?? 0) === 0
        ? `
      <div class="empty">
        <div class="empty__icon">${icon('i-search')}</div>
        <h3>아직 수집 전입니다</h3>
        <p>크롤러가 이 카테고리의 첫 라운드를 마치면 여기에 매물이 표시됩니다.</p>
      </div>`
        : `
      <div class="empty">
        <div class="empty__icon">${icon('i-search')}</div>
        <h3>조건에 맞는 매물이 없습니다</h3>
        <p>선택하신 필터(브랜드·플랫폼·가격)를 변경하거나 필터 초기화 후 다시 검색해보세요.</p>
        <button type="button" class="btn-dark" data-action="reset">필터 초기화하기</button>
      </div>`;

    renderPager(state);
    return;
  }

  grid.innerHTML = state.items.map(cardHtml).join('');
  renderPager(state);
}

/**
 * 목록 아래. 무한 스크롤이므로 버튼이 아니라 상태만 보여준다.
 *
 * #pager 자체가 IntersectionObserver의 sentinel이다(main.js). 이 요소가 비어
 * 있으면 높이가 0이 되어 관찰이 안 걸리므로, 더 받을 게 있을 때는 반드시
 * 눈에 보이는 내용을 채워 둔다.
 *
 * IntersectionObserver가 없는 구형 브라우저를 위해 버튼도 남긴다 —
 * state.autoLoad가 false면 스크롤 대신 버튼이 다음 장을 부른다.
 */
export function renderPager(state) {
  const pager = el('pager');
  if (!pager) return;

  if (state.status === 'loading' || state.status === 'error' || state.total === 0) {
    pager.innerHTML = '';
    return;
  }

  const shown = state.items.length.toLocaleString('ko-KR');
  const total = state.total.toLocaleString('ko-KR');

  if (!state.hasNext) {
    pager.innerHTML = `<span>총 ${total}개 매물을 모두 불러왔습니다</span>`;
    return;
  }

  if (state.autoLoad) {
    pager.innerHTML =
      state.status === 'appending'
        ? `<span class="pager__loading">${icon('i-rotate', 'spin')}불러오는 중…</span>`
        : `<span>${shown} / ${total}</span>`;
    return;
  }

  const busy = state.status === 'appending';

  pager.innerHTML = `
    <button type="button" class="btn-more" data-action="more" ${busy ? 'disabled' : ''}>
      ${icon('i-plus')}
      <span>${busy ? '불러오는 중…' : `매물 더보기 (${shown} / ${total})`}</span>
    </button>`;
}

/* --------------------------------------------------------------- 추천 레일 */

/** 대문 추천 레일. 한 쪽에 pageSize장씩, 좌우 화살표와 점으로 넘긴다. */
export function renderReco(reco) {
  const grid = el('recoGrid');
  const dots = el('recoDots');
  if (!grid || !dots) return;

  const pageCount = Math.max(Math.ceil(reco.items.length / reco.pageSize), 1);
  const start = reco.page * reco.pageSize;
  const slice = reco.items.slice(start, start + reco.pageSize);

  grid.innerHTML = slice.length
    ? slice.map(cardHtml).join('')
    : SKELETON.repeat(reco.pageSize);

  dots.innerHTML = Array.from({ length: pageCount })
    .map((_, i) => `<button type="button" class="${i === reco.page ? 'on' : ''}" data-recodot="${i}" aria-label="${i + 1}쪽"></button>`)
    .join('');

  el('recoPage').textContent = String(reco.page + 1);
  el('recoPages').textContent = String(pageCount);
}
