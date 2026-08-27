// web/js/api.js
//
// 백엔드 호출 전부. 화면 코드는 fetch를 직접 만지지 않는다 —
// 계약(ListingOut)이 바뀌면 이 파일과 render.js만 보면 되게 하려는 것이다.

import { PRICE_UNLIMITED, toQueryBrand } from './state.js';

/**
 * 백엔드가 프론트를 같은 출처에서 서빙하므로(app/main.py의 StaticFiles mount)
 * 빈 문자열 = 상대 경로가 기본이다. 포트를 맞출 것도, CORS를 열 것도 없다.
 *
 * 프론트만 따로 호스팅하는 경우에만 절대 주소를 넣고, 그때는 백엔드 .env의
 * ALLOWED_ORIGINS에 그 출처를 추가한다.
 */
export const API_BASE = '';

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });

  if (!res.ok) {
    throw new Error(`서버가 ${res.status}로 응답했습니다.`);
  }

  return res.json();
}

/**
 * 필터 상태 → 쿼리스트링.
 *
 * 필터는 서버가 건다. 받아온 한 페이지만 걸러내면 "전체에서 가장 싼 매물"이
 * 아니라 "이 페이지에서 가장 싼 매물"이 된다. '전체'와 기본값은 아예 보내지
 * 않는다 — 파라미터 부재가 곧 "필터 없음"이다.
 */
export function buildQuery(filters, offset, limit) {
  const q = new URLSearchParams();

  if (filters.category !== 'all') q.set('category', filters.category);
  if (filters.brand && filters.brand !== '전체') q.set('brand', toQueryBrand(filters.brand));
  if (filters.source && filters.source !== '전체') q.set('source', filters.source);
  if (filters.q) q.set('search', filters.q);
  if (filters.min > 0) q.set('min_price', String(filters.min));
  if (filters.max < PRICE_UNLIMITED) q.set('max_price', String(filters.max));
  if (filters.sort) q.set('order_by', filters.sort);
  // 인증 매물만. 기본값(false)은 보내지 않는다 — 부재가 곧 "필터 없음"이다.
  if (filters.authenticatedOnly) q.set('authenticated_only', 'true');

  q.set('limit', String(limit));
  q.set('offset', String(offset));

  return q;
}

/**
 * 매물 목록.
 * @returns {Promise<{total:number,count:number,limit:number,offset:number,has_next:boolean,items:object[]}>}
 */
export function fetchListings(filters, offset, limit, signal) {
  return getJSON(`${API_BASE}/api/products?${buildQuery(filters, offset, limit)}`, signal);
}

/** 필터 선택지와 수집 현황 (브랜드·수집처·카테고리별 건수). */
export function fetchMeta(signal) {
  return getJSON(`${API_BASE}/api/meta`, signal);
}

/**
 * 대문 추천 레일용. 최신순 상위 n건.
 *
 * 화면 필터와 무관하게 항상 같은 조건이라 filters를 받지 않는다 — 대문은
 * "지금 뭐가 올라와 있나"를 보여주는 자리다.
 */
export async function fetchReco(limit = 50) {
  const q = new URLSearchParams({ limit: String(limit), offset: '0', order_by: 'latest' });
  const data = await getJSON(`${API_BASE}/api/products?${q}`);

  return data.items;
}
