// reluxe/js/state.js
//
// 화면 상태 전부가 아래 state 객체 하나다. DOM에 상태를 숨겨두지 않는다 —
// "상태를 바꾸고 → 다시 그린다"는 한 방향 흐름이 프레임워크 없이 화면이
// 안 꼬이게 하는 유일한 규율이고, 그 규율의 전제가 상태의 단일 출처다.

export const PAGE_SIZE = 24;

export const CATEGORY_LABELS = Object.freeze({
  all: "전체", bag: "가방", watch: "시계", jewelry: "주얼리", apparel: "의류", shoes: "신발",
});

export const DEFAULT_FILTERS = Object.freeze({
  category: "all", // 대문의 기본. 서버에는 "all"일 때 category를 안 보낸다 = 전체
  brand: "전체",
  source: "전체",
  q: "",
  min: null, // 만원 단위. null = 제한 없음
  max: null,
  sort: "latest", // 서버 order_by 값과 동일한 어휘를 쓴다
});

/** 서버 order_by 화이트리스트와 1:1. 여기 없는 값은 latest로 떨어진다. */
export const SORT_OPTIONS = Object.freeze([
  { value: "latest", label: "최신순" },
  { value: "oldest", label: "오래된순" },
  { value: "price_asc", label: "최저가순" },
  { value: "price_desc", label: "최고가순" },
]);

export const state = {
  mode: "home", // "home"(대문: 필터 없음) | "list"(카테고리·검색 목록)
  // IntersectionObserver 가용 여부. main.js가 부팅 때 한 번 채운다.
  // true면 전 화면이 스크롤 자동 로딩이고, false(구형 브라우저)면
  // 렌더가 "더 보기" 버튼을 폴백으로 그린다.
  autoLoad: true,
  filters: { ...DEFAULT_FILTERS },
  items: [], // 지금까지 받아온 매물 (더 보기로 누적)
  total: 0,
  offset: 0,
  hasNext: false,
  status: "loading", // idle(대문 스크롤 대기) | loading(첫 로드) | ready | appending | error
  errorMessage: "",
  meta: null, // /api/meta 응답. 브랜드 선택지·전체 건수·수집 시각
};

/**
 * 켜져 있는 필터 개수. 필터 버튼 배지에 쓴다.
 * 카테고리는 세지 않는다 — 필터가 아니라 화면의 축이고, 카드가 그 상태를
 * 이미 보여준다. 정렬도 세지 않는다 — 결과를 좁히는 게 아니라 순서만 바꾸는 조작이라,
 * 배지에 들어가면 "필터가 걸려서 안 보이는 매물이 있다"는 신호가 거짓이 된다.
 */
export function activeFilterCount(f) {
  let n = 0;
  if (f.brand !== "전체") n += 1;
  if (f.source !== "전체") n += 1;
  if (f.q) n += 1;
  if (f.min != null || f.max != null) n += 1;
  return n;
}

/**
 * 필터 → 주소창. 새로고침해도, 링크를 공유해도 같은 화면이 나오게 한다.
 * 페이지 이동이 아니므로 replaceState — 뒤로가기 스택을 오염시키지 않는다.
 */
export function writeFiltersToURL(f) {
  const q = new URLSearchParams();
  if (f.category !== "all") q.set("cat", f.category);
  if (f.brand !== "전체") q.set("brand", f.brand);
  if (f.source !== "전체") q.set("source", f.source);
  if (f.q) q.set("q", f.q);
  if (f.min != null) q.set("min", String(f.min));
  if (f.max != null) q.set("max", String(f.max));
  if (f.sort !== "latest") q.set("sort", f.sort);
  const qs = q.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

/** 주소창 → 필터. 첫 진입 때 한 번 읽는다. */
export function readFiltersFromURL() {
  const q = new URLSearchParams(location.search);
  const num = (v) => {
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  const sortRaw = q.get("sort");
  const catRaw = q.get("cat");
  return {
    // cat 파라미터 부재 = 전체(대문). "all"이라는 값 자체는 URL에 안 쓴다.
    category:
      catRaw && catRaw !== "all" && catRaw in CATEGORY_LABELS ? catRaw : "all",
    brand: q.get("brand") || "전체",
    source: q.get("source") || "전체",
    q: q.get("q") || "",
    min: q.has("min") ? num(q.get("min")) : null,
    max: q.has("max") ? num(q.get("max")) : null,
    sort: SORT_OPTIONS.some((o) => o.value === sortRaw) ? sortRaw : "latest",
  };
}
