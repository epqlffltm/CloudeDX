// reluxe/js/render.js
//
// 상태(state.js)를 받아 화면을 그린다. 여기 함수들은 상태를 바꾸지 않는다 —
// 읽고 그리기만 한다. 카드 목록은 조각 수정 없이 통째로 재생성한다.
// limit 24장 규모에서 innerHTML 재생성은 밀리초 단위라, diff 없이도 충분하다.

import { activeFilterCount, CATEGORY_LABELS } from "./state.js";

/* ---------------------------------------------------------------------------
   가격 슬라이더 스텝 테이블 (만원 단위)

   선형 스케일이 아니라 단계식이다: 매물 가격이 0~3000만원에 퍼져 있는데
   선형으로 펴면 실사용 구간(0~500만)이 트랙의 1/6, 손가락 몇 픽셀에 몰린다.
   구간별로 눈금 간격을 달리해 어느 가격대든 비슷한 손맛으로 잡히게 한다.
   마지막 인덱스 하나는 눈금이 아니라 "제한 없음"이다.
--------------------------------------------------------------------------- */

const PRICE_STEPS = [];
for (let v = 0; v <= 100; v += 10) PRICE_STEPS.push(v); //     ~100만: 10만 간격
for (let v = 120; v <= 500; v += 20) PRICE_STEPS.push(v); //   ~500만: 20만 간격
for (let v = 550; v <= 1000; v += 50) PRICE_STEPS.push(v); // ~1000만: 50만 간격
for (let v = 1100; v <= 3000; v += 100) PRICE_STEPS.push(v); // ~3000만: 100만 간격

/** 슬라이더의 마지막 인덱스. 이 자리는 값이 아니라 "제한 없음"이다. */
export const RANGE_MAX_INDEX = PRICE_STEPS.length;

/** 인덱스 → 만원. 최고가 썸이 끝까지 가면 null(제한 없음). */
export function stepValue(index, kind) {
  if (index >= PRICE_STEPS.length) {
    return kind === "max" ? null : PRICE_STEPS[PRICE_STEPS.length - 1];
  }
  return PRICE_STEPS[index];
}

/** 만원 → 가장 가까운 인덱스. 입력칸에 친 정밀값을 슬라이더 위치로 근사한다. */
export function stepIndexFor(value, kind) {
  if (value == null) return kind === "max" ? RANGE_MAX_INDEX : 0;
  let best = 0;
  for (let i = 0; i < PRICE_STEPS.length; i += 1) {
    if (Math.abs(PRICE_STEPS[i] - value) < Math.abs(PRICE_STEPS[best] - value)) best = i;
  }
  return best;
}

const el = (id) => document.getElementById(id);

/**
 * 수집 사이트 제목이 그대로 들어오므로 이스케이프는 선택이 아니다.
 * React가 자동으로 해주던 일을 여기서는 손으로 한다 — 크롤링 데이터에
 * <script>가 섞여 들어오는 순간을 막는 유일한 방어선이다.
 */
export function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 4,300,000 → "₩4,300,000". null은 가격을 못 읽은 매물이다 — 지어내지 않는다. */
function priceHtml(price) {
  if (price == null) {
    return `<span class="card__price unknown">가격 미상</span>`;
  }
  return `<span class="card__price">₩${price.toLocaleString("ko-KR")}</span>`;
}

/** ISO 시각 → "12분 전" 같은 상대 표기 */
function relTime(iso) {
  if (!iso) return null;
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff) || diff < 0) return null;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  return `${Math.floor(hr / 24)}일 전`;
}

/* ---------------------------------------------------------------------------
   필터 칩
--------------------------------------------------------------------------- */

/**
 * 칩 한 벌을 다시 그린다. 브랜드·플랫폼은 /api/meta의 실제 수집값(문자열)에
 * "전체"를 앞세우고, 정렬은 {value, label} 쌍(withAll=false)을 그대로 쓴다.
 */
export function renderChips(containerId, values, active, { withAll = false } = {}) {
  const items = (withAll ? ["전체", ...values] : values).map((v) =>
    typeof v === "string" ? { value: v, label: v } : v,
  );
  el(containerId).innerHTML = items
    .map(
      (it) => `
      <button type="button" class="chip ${it.value === active ? "on" : ""}"
              data-chip="${containerId}" data-value="${escapeHtml(it.value)}">
        ${escapeHtml(it.label)}
      </button>`,
    )
    .join("");
}

export function renderFilterBadge(filters) {
  const n = activeFilterCount(filters);
  const badge = el("filterBadge");
  badge.textContent = n || "";
  badge.classList.toggle("on", n > 0);
}

/* ---------------------------------------------------------------------------
   목록 위 요약줄과 카테고리 카드 건수
--------------------------------------------------------------------------- */

export function renderMetaLine(state) {
  if (state.status === "idle") {
    // 대문의 스크롤 대기 상태 — 아직 아무것도 안 불렀는데 "총 0건"이라
    // 적어두면 거짓말이다. 첫 로드가 뜨면 load()가 다시 채운다.
    el("resultMeta").textContent = "";
    return;
  }
  const parts = [`총 <strong>${state.total.toLocaleString("ko-KR")}</strong>건`];
  const t = relTime(state.meta?.last_crawled_at);
  if (t) parts.push(`${t} 수집`);
  el("resultMeta").innerHTML = parts.join(" · ");
}

/** 카테고리 카드의 건수와 활성 표시. meta가 아직 없으면 건수는 말줄임으로 둔다. */
export function renderCategoryCards(meta, activeCategory) {
  for (const card of document.querySelectorAll("[data-category]")) {
    const on = card.dataset.category === activeCategory;
    card.classList.toggle("cat--active", on);
    card.setAttribute("aria-pressed", String(on));
  }

  for (const span of document.querySelectorAll("[data-count]")) {
    const n = meta?.categories?.[span.dataset.count];
    span.textContent = n == null ? "…" : `${n.toLocaleString("ko-KR")}개 매물`;
  }

}

/**
 * 목록 제목. 검색 중이면 카테고리명 대신 검색어를 보여준다 —
 * "가방"이라 적힌 목록에 시계 검색 결과가 섞여 보이는 혼선을 막는다.
 */
export function renderTitle(filters) {
  el("listTitle").textContent = filters.q
    ? `'${filters.q}'`
    : CATEGORY_LABELS[filters.category];
}

/* ---------------------------------------------------------------------------
   매물 카드
--------------------------------------------------------------------------- */

/**
 * 카드 한 장. 전체가 원문으로 가는 진짜 <a>다 — div+onClick이 아니라 링크라서
 * 모바일 길게 눌러 미리보기·새 탭 열기가 공짜로 따라온다. 거래는 원문에서
 * 이루어지는 서비스라, 카드의 유일한 행동이 "원문으로 간다"인 게 맞다.
 */
function cardHtml(item) {
  const title = escapeHtml(item.title);
  const thumb = item.image_url
    ? `<img src="${escapeHtml(item.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
    : `<span class="noimg">이미지 없음</span>`;

  return `
  <a class="card" href="${escapeHtml(item.item_url)}" target="_blank" rel="noopener noreferrer">
    <span class="card__thumb">
      ${thumb}
      <span class="badge-brand">${escapeHtml(item.brand)}</span>
      <span class="badge-source">${escapeHtml(item.source)}</span>
    </span>
    <span class="card__body">
      <h3 class="card__title">${title}</h3>
      <span class="card__pricing">
        <span class="lbl">판매가격</span>
        ${priceHtml(item.price)}
      </span>
    </span>
    <span class="card__go">
      매물 바로가기
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
    </span>
  </a>`;
}

const skeletonHtml = `<div class="skel" aria-hidden="true"></div>`;

/** 목록 영역 전체를 상태에서 다시 그린다. 여기가 이 화면의 심장이다. */
export function renderList(state) {
  const grid = el("grid");

  if (state.status === "idle") {
    // 대문 모드의 초기 상태 — 목록 영역이 뷰포트에 다가오면 그때 첫 로드가 뜬다.
    grid.innerHTML = "";
    renderPager(state);
    return;
  }

  if (state.status === "loading") {
    grid.innerHTML = skeletonHtml.repeat(8);
    renderPager(state);
    return;
  }

  if (state.status === "error") {
    grid.innerHTML = `
      <div class="state">
        <h3>매물을 불러오지 못했습니다</h3>
        <p>${escapeHtml(state.errorMessage)}<br/>백엔드 주소는 js/api.js 맨 위에서 바꿉니다.</p>
        <button type="button" class="btn-reset" data-action="retry">다시 시도</button>
      </div>`;
    renderPager(state);
    return;
  }

  if (state.items.length === 0) {
    // 빈 화면 두 가지를 구분한다: 아직 아무것도 수집 전 vs 필터가 다 걸러냄.
    // 사용자가 해야 할 일이 다르다 — 전자는 기다리기, 후자는 필터 풀기.
    // 콜드스타트 판정은 카테고리 단위다 — 시계는 0인데 가방이 4만 건일 수 있다.
    // 단 "all"(대문·전체)은 categories에 키가 없다 — 전체 재고는 total_items다.
    // 이걸 빼먹으면 전체 스코프의 검색 0건이 "수집 전"이라는 거짓 문구가 된다.
    const stock =
      state.filters.category === "all"
        ? state.meta?.total_items
        : state.meta?.categories?.[state.filters.category];
    const coldStart = (stock ?? 0) === 0;
    const label = CATEGORY_LABELS[state.filters.category];
    grid.innerHTML = coldStart
      ? `
      <div class="state">
        <h3>${label} 카테고리는 아직 수집 전입니다</h3>
        <p>크롤러가 이 카테고리의 첫 라운드를 마치면 여기에 매물이 표시됩니다.</p>
      </div>`
      : `
      <div class="state">
        <h3>조건에 맞는 매물이 없습니다</h3>
        <p>필터를 풀거나 검색어를 바꿔 보세요.</p>
        <button type="button" class="btn-reset" data-action="reset">필터 초기화</button>
      </div>`;
    renderPager(state);
    return;
  }

  grid.innerHTML = state.items.map(cardHtml).join("");
  renderPager(state);
}

/* ---------------------------------------------------------------------------
   목록 아래 — 진행 상태와 더 보기
--------------------------------------------------------------------------- */

export function renderPager(state) {
  const pager = el("pager");

  if (
    state.status === "idle" ||
    state.status === "loading" ||
    state.status === "error" ||
    state.total === 0
  ) {
    pager.innerHTML = "";
    return;
  }

  const shown = state.items.length;
  const status = `
    <div class="pager__status">
      <span>총 <strong>${state.total.toLocaleString("ko-KR")}</strong>개 매물 중</span>
      <span class="dot" aria-hidden="true"></span>
      <span><strong class="dark">${shown.toLocaleString("ko-KR")}</strong>개 표시</span>
    </div>`;

  if (state.hasNext && state.autoLoad) {
    // 스크롤이 곧 "더 보기"다 — 대문·목록 공통. 버튼 없이 상태만 보여준다.
    pager.innerHTML = `
      ${status}
      ${state.status === "appending" ? '<div class="pager__end">불러오는 중…</div>' : ""}`;
    return;
  }

  // IntersectionObserver가 없는 구형 브라우저 폴백 — 버튼이 스크롤을 대신한다.
  if (state.hasNext) {
    const appending = state.status === "appending";
    pager.innerHTML = `
      ${status}
      <button type="button" class="btn-more ${appending ? "loading" : ""}"
              data-action="more" ${appending ? "disabled" : ""}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
          ${appending ? '<path d="M21 12a9 9 0 1 1-6.2-8.56"/>' : '<path d="M12 5v14M5 12h14"/>'}
        </svg>
        <span>${appending ? "불러오는 중…" : "매물 더보기"}</span>
      </button>`;
  } else {
    pager.innerHTML = `
      ${status}
      <div class="pager__end">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4 12.5 5 5L20 6.5"/></svg>
        <span>모든 매물을 불러왔습니다</span>
      </div>`;
  }
}

/* ---------------------------------------------------------------------------
   필터 입력값 되돌려 그리기 (초기화·URL 복원 때)
--------------------------------------------------------------------------- */

export function renderFilterInputs(filters) {
  el("minPrice").value = filters.min ?? "";
  el("maxPrice").value = filters.max ?? "";
  renderRange(stepIndexFor(filters.min, "min"), stepIndexFor(filters.max, "max"));
  const input = el("searchInput");
  input.value = filters.q;
  input.closest(".search").classList.toggle("has-value", Boolean(filters.q));
}

/** 만원 값 표기: 1250 → "1,250만원" */
function manwon(v) {
  return `${v.toLocaleString("ko-KR")}만원`;
}

/**
 * 슬라이더 시각 상태(썸 위치·채움·라벨)를 인덱스 기준으로 그린다.
 * 드래그 중에는 매 input마다, 확정 시에는 renderFilterInputs를 통해 불린다.
 */
export function renderRange(minIdx, maxIdx) {
  const lo = el("rangeMin");
  const hi = el("rangeMax");
  lo.max = RANGE_MAX_INDEX;
  hi.max = RANGE_MAX_INDEX;
  lo.value = minIdx;
  hi.value = maxIdx;

  const pct = (i) => (i / RANGE_MAX_INDEX) * 100;
  const fill = el("rangeFill");
  fill.style.left = `${pct(minIdx)}%`;
  fill.style.right = `${100 - pct(maxIdx)}%`;

  // 두 썸이 한쪽 끝에 겹치면 아래 깔린 쪽을 잡을 수 없다.
  // 최저 썸이 상반부에 있을 때만 위로 올려 서로를 가리지 않게 한다.
  lo.style.zIndex = minIdx > RANGE_MAX_INDEX / 2 ? 4 : 3;

  const min = stepValue(minIdx, "min");
  const max = stepValue(maxIdx, "max");
  el("rangeLabel").textContent =
    minIdx === 0 && max == null
      ? "전체"
      : `${min === 0 ? "0원" : manwon(min)} ~ ${max == null ? "제한 없음" : manwon(max)}`;
}

/** 시트 하단 버튼에 현재 결과 수를 실시간으로 비춘다 */
export function renderSheetCTA(state) {
  el("filterClose").textContent =
    state.status === "ready" ? `매물 ${state.total.toLocaleString("ko-KR")}건 보기` : "매물 보기";
}


/** 대문 추천 레일. escapeHtml 규율은 매물 카드와 동일하다 — 크롤 데이터다. */
export function renderRecoRail(items) {
  const section = el("recoSection");

  if (!items.length) {
    section.hidden = true; // 전 카테고리 수집 전 — 빈 레일을 보여줄 이유가 없다
    return;
  }

  el("recoViewport").innerHTML = items
    .map(
      (it) => `
    <a class="rcard" href="${escapeHtml(it.item_url)}" target="_blank" rel="noopener noreferrer">
      <div class="rcard__thumb">
        ${it.image_url ? `<img src="${escapeHtml(it.image_url)}" alt="" loading="lazy" />` : ""}
        <span class="rcard__cat">${CATEGORY_LABELS[it.category] ?? it.category}</span>
      </div>
      <div class="rcard__body">
        <div class="rcard__title">${escapeHtml(it.title)}</div>
        <div class="rcard__price">${it.price ?? "가격 미상"}</div>
      </div>
    </a>`,
    )
    .join("");
  section.hidden = false;
}
