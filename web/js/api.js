// reluxe/js/api.js
//
// 백엔드 호출 전부. 화면의 다른 코드는 fetch를 직접 만지지 않는다 —
// 계약(ListingOut)이 바뀌면 이 파일과 render.js만 보면 되게 하기 위해서다.

/**
 * 백엔드 주소. 프론트를 백엔드가 같은 출처에서 서빙하므로(app/main.py의
 * StaticFiles mount) 빈 문자열 = 상대 경로가 기본이다 — 포트를 맞출 것도,
 * CORS를 열 것도 없다. 화면과 API의 주소가 하나다.
 *
 * 프론트만 따로 호스팅하는 경우(별도 정적 호스팅)에만 절대 주소를 넣고,
 * 그때는 백엔드 .env의 ALLOWED_ORIGINS에 그 출처를 추가한다.
 */
export const API_BASE = "";

/**
 * 매물 한 건. 백엔드 ListingOut과 필드가 1:1이다.
 * @typedef {Object} Listing
 * @property {number} id
 * @property {string} source     수집처 ('당근마켓' | '중고나라')
 * @property {string} title      정제 제목 (없으면 원제목)
 * @property {string} brand
 * @property {string} category   지금은 전부 'bag'
 * @property {number|null} price 원 단위. 파싱 실패면 null
 * @property {string|null} image_url
 * @property {string} item_url   원문 매물 주소
 */

/**
 * 필터 상태를 쿼리스트링으로 바꾼다.
 * 서버 파라미터명(brand/source/search/min_price/max_price)은
 * /api/crawled-items와 공유되는 CrawledItemFilterParams 그대로다.
 * '전체'와 빈 값은 서버에 보내지 않는다 — 파라미터 부재가 곧 "필터 없음"이다.
 */
export function buildQuery(filters, offset, limit) {
  const q = new URLSearchParams();
  // "all"은 서버 어휘에 없다 — category 미전송이 곧 전체다.
  if (filters.category !== "all") q.set("category", filters.category);
  if (filters.brand && filters.brand !== "전체") q.set("brand", filters.brand);
  if (filters.source && filters.source !== "전체") q.set("source", filters.source);
  if (filters.q) q.set("search", filters.q);
  // 입력은 만원 단위, 서버는 원 단위
  if (filters.min != null) q.set("min_price", String(filters.min * 10_000));
  if (filters.max != null) q.set("max_price", String(filters.max * 10_000));
  // 정렬은 서버가 한다 — 받아온 한 페이지만 재정렬하면 "전체에서 가장 싼
  // 매물"이 아니라 "이 페이지에서 가장 싼 매물"이 된다. 기본값은 생략.
  if (filters.sort && filters.sort !== "latest") q.set("order_by", filters.sort);
  q.set("limit", String(limit));
  q.set("offset", String(offset));
  return q;
}

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`서버가 ${res.status}로 응답했습니다.`);
  }
  return res.json();
}

/**
 * 매물 목록. 정렬은 서버가 최신 발견 순으로 고정한다.
 * @returns {Promise<{total:number, count:number, limit:number, offset:number, has_next:boolean, items:Listing[]}>}
 */
export function fetchListings(filters, offset, limit, signal) {
  const q = buildQuery(filters, offset, limit);
  return getJSON(`${API_BASE}/api/products?${q}`, signal);
}

/**
 * 필터 선택지와 수집 상태.
 * @returns {Promise<{brands:string[], sources:string[], total_items:number, last_crawled_at:string|null, crawler:object}>}
 */
export function fetchMeta(signal) {
  return getJSON(`${API_BASE}/api/meta`, signal);
}
