// web/js/state.js
//
// 화면 상태와 상수. DOM에 상태를 숨기지 않는다 —
// "상태를 바꾼다 → 다시 그린다"는 한 방향 흐름을 지키기 위한 단일 출처다.

export const PAGE_SIZE = 30;

/** 슬라이더 상한. 이 값 이상이면 "무제한"으로 본다 (원 단위). */
export const PRICE_CAP = 20_000_000;
export const PRICE_UNLIMITED = 100_000_000;

export const CATEGORY_TABS = [
  { id: 'all',     name: '전체 카테고리',    icon: 'i-sparkles' },
  { id: 'bag',     name: '가방 (Bags)',      icon: 'i-bag' },
  { id: 'watch',   name: '시계 (Watches)',   icon: 'i-watch' },
  { id: 'jewelry', name: '주얼리 (Jewelry)', icon: 'i-gem' },
  { id: 'apparel', name: '의류 (Apparel)',   icon: 'i-shirt' },
  { id: 'shoes',   name: '신발 (Shoes)',     icon: 'i-shoe' },
];

/** 대문 카테고리 카드. 준비중 표기는 수집 대상이 아직 아니라는 뜻이다. */
export const CATEGORY_CARDS = [
  { id: 'bag',     title: '가방',   sub: 'Bags & Handbags', icon: 'i-bag',   ready: true },
  { id: 'watch',   title: '시계',   sub: 'Luxury Watches',  icon: 'i-watch', ready: true },
  { id: 'jewelry', title: '주얼리', sub: 'Fine Jewelry',    icon: 'i-gem',   ready: false },
  { id: 'apparel', title: '의류',   sub: 'Apparel',         icon: 'i-shirt', ready: false },
  { id: 'shoes',   title: '신발',   sub: 'Shoes',           icon: 'i-shoe',  ready: false },
];

export const CATEGORY_LABELS = Object.fromEntries(
  CATEGORY_TABS.map((c) => [c.id, c.name]),
);

/** 정렬. value는 서버 order_by 어휘와 같다 — 변환 없이 그대로 넘긴다. */
export const SORT_OPTIONS = [
  { value: 'price_asc',  label: '최저가순' },
  { value: 'price_desc', label: '최고가순' },
  { value: 'latest',     label: '최신순' },
];

export const PRICE_PRESETS = [
  { label: '전체',          min: 0,          max: PRICE_UNLIMITED },
  { label: '100만원 이하',  min: 0,          max: 1_000_000 },
  { label: '100~300만',     min: 1_000_000,  max: 3_000_000 },
  { label: '300~500만',     min: 3_000_000,  max: 5_000_000 },
  { label: '500~1,000만',   min: 5_000_000,  max: 10_000_000 },
  { label: '1,000만원 이상', min: 10_000_000, max: PRICE_UNLIMITED },
];

export const POPULAR_TERMS = [
  '샤넬 22백', '롤렉스 서브마리너', '에르메스 버킨',
  '디올 레이디백', '까르띠에 러브링', '루이비통 온더고',
];

export const DEFAULT_FILTERS = Object.freeze({
  category: 'all',
  brand: '전체',
  source: '전체',
  q: '',
  min: 0,                 // 원 단위
  max: PRICE_UNLIMITED,
  sort: 'price_asc',      // 화면 기본은 최저가순
});

export const state = {
  mode: 'home',                        // 'home' | 'list'
  filters: { ...DEFAULT_FILTERS },
  items: [],
  total: 0,
  offset: 0,
  hasNext: false,
  status: 'loading',                   // loading | ready | appending | error
  // IntersectionObserver 가용 여부. main.js가 부팅 때 한 번 채운다.
  // true면 스크롤이 곧 "더 보기"이고, false(구형 브라우저)면 렌더가 버튼을 그린다.
  autoLoad: true,
  errorMessage: '',
  meta: null,
  reco: { items: [], page: 0, pageSize: 10 },
};

/**
 * 백엔드 브랜드는 한글(샤넬), 화면 칩은 영문 대문자(CHANEL)다.
 * 표기만 바꾸고 질의는 한글로 되돌린다. 목록에 없으면 원문을 그대로 쓴다 —
 * 브랜드를 추가했을 때 화면에서 사라지는 것보다 한글로 뜨는 편이 낫다.
 */
const BRAND_DISPLAY = {
  샤넬: 'CHANEL', 구찌: 'GUCCI', 루이비통: 'LOUIS VUITTON', 에르메스: 'HERMÈS',
  프라다: 'PRADA', 디올: 'DIOR', 고야드: 'GOYARD', 셀린느: 'CELINE',
  보테가: 'BOTTEGA VENETA', 생로랑: 'SAINT LAURENT', 발렌시아가: 'BALENCIAGA',
  버버리: 'BURBERRY', 롤렉스: 'ROLEX', 오메가: 'OMEGA', 까르띠에: 'CARTIER',
  불가리: 'BULGARI', 티파니: 'TIFFANY & CO.', 반클리프: 'VAN CLEEF & ARPELS',
  펜디: 'FENDI', 미우미우: 'MIU MIU', 마르지엘라: 'MAISON MARGIELA',
  톰브라운: 'THOM BROWNE', 바오바오: 'BAO BAO', 몽클레르: 'MONCLER',
};

const BRAND_QUERY = Object.fromEntries(
  Object.entries(BRAND_DISPLAY).map(([ko, en]) => [en, ko]),
);

export const toDisplayBrand = (ko) => BRAND_DISPLAY[ko] ?? ko;
export const toQueryBrand = (display) => BRAND_QUERY[display] ?? display;

/** 필터 → 주소창. 새로고침하거나 링크를 공유해도 같은 화면이 나온다. */
export function writeFiltersToURL(f) {
  const q = new URLSearchParams();
  if (f.category !== 'all') q.set('cat', f.category);
  if (f.brand !== '전체') q.set('brand', f.brand);
  if (f.source !== '전체') q.set('source', f.source);
  if (f.q) q.set('q', f.q);
  if (f.min > 0) q.set('min', String(f.min));
  if (f.max < PRICE_UNLIMITED) q.set('max', String(f.max));
  if (f.sort !== DEFAULT_FILTERS.sort) q.set('sort', f.sort);
  const qs = q.toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

/** 주소창 → 필터. 첫 진입 때 한 번 읽는다. */
export function readFiltersFromURL() {
  const p = new URLSearchParams(location.search);
  const num = (v, fallback) => {
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n : fallback;
  };
  const cat = p.get('cat');
  const sort = p.get('sort');

  return {
    category: cat && CATEGORY_LABELS[cat] ? cat : 'all',
    brand: p.get('brand') || '전체',
    source: p.get('source') || '전체',
    q: p.get('q') || '',
    min: p.has('min') ? num(p.get('min'), 0) : 0,
    max: p.has('max') ? num(p.get('max'), PRICE_UNLIMITED) : PRICE_UNLIMITED,
    sort: SORT_OPTIONS.some((o) => o.value === sort) ? sort : DEFAULT_FILTERS.sort,
  };
}
