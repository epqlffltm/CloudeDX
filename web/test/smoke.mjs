// web/test/smoke.mjs
//
// 부팅 스모크 테스트. index.html을 jsdom에 올리고 js/main.js를 실제 모듈로
// 실행해서, 대문과 결과 화면이 스텁 API 응답으로 제대로 그려지는지 본다.
//
// 단위 테스트로는 안 잡히는 종류를 잡으려는 것이다 — 함수는 전부 멀쩡한데
// 부팅 순서나 id 하나가 어긋나 화면이 통째로 백지가 되는 사고.
//
// 실행: npm i --no-save jsdom && node web/test/smoke.mjs

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, '..');

/* ------------------------------------------------------------ 가짜 백엔드 */

const ITEMS = [
  { id: 1, source: '중고나라', title: '롤렉스 서브마리너 124060', brand: '롤렉스',
    category: 'watch', price: 17_200_000, image_url: null, item_url: 'https://ex.test/w1' },
  { id: 2, source: '번개장터', title: '오메가 씨마스터 300', brand: '오메가',
    category: 'watch', price: 3_800_000, image_url: null, item_url: 'https://ex.test/w2' },
  { id: 3, source: '당근마켓', title: '샤넬 클래식 미디움 캐비어', brand: '샤넬',
    category: 'bag', price: 9_800_000, image_url: null, item_url: 'https://ex.test/b1' },
];

const json = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

const calls = [];

function stubFetch(url) {
  const path = String(url);
  calls.push(path);

  if (path.includes('/api/meta')) {
    return json({
      sources: ['당근마켓', '중고나라', '번개장터'],
      brands: ['샤넬', '롤렉스', '오메가'],
      categories: { bag: 1, watch: 2, jewelry: 0, apparel: 0, shoes: 0 },
      brands_by_category: { bag: ['샤넬'], watch: ['롤렉스', '오메가', '까르띠에'] },
      total_items: 3,
      last_crawled_at: new Date().toISOString(),
      crawler: { is_running: false },
    });
  }

  if (path.includes('/api/products')) {
    // 무한 스크롤 검증용: 첫 장은 has_next=true, 다음 장부터 false.
    const offset = Number(new URLSearchParams(path.split('?')[1] ?? '').get('offset') ?? 0);
    return json({
      total: 6, count: 3, limit: 30, offset,
      has_next: offset === 0,
      items: ITEMS.map((i) => ({ ...i, id: i.id + offset })),
    });
  }

  if (path.includes('/api/auth/me')) {
    return json(null);
  }

  return json({ detail: 'not found' });
}

/* ------------------------------------------------------------------ 부팅 */

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => errors.push(e));

const dom = new JSDOM(readFileSync(resolve(webDir, 'index.html'), 'utf8'), {
  url: 'http://localhost:8000/?cat=watch',
  runScripts: 'outside-only',
  pretendToBeVisual: true,
  virtualConsole: vc,
});

const { window } = dom;
window.fetch = (url) => stubFetch(url);
window.scrollTo = () => {};

// jsdom에는 IntersectionObserver가 없다. 관찰 대상이 등록되면 즉시 교차한 것으로
// 통보해서, 무한 스크롤이 다음 장을 실제로 요청하는지 확인한다.
const observed = [];
window.IntersectionObserver = class {
  constructor(cb) { this.cb = cb; }
  observe(node) { observed.push(node); this.cb([{ isIntersecting: true, target: node }]); }
  unobserve() {}
  disconnect() {}
};

globalThis.window = window;
globalThis.document = window.document;
globalThis.location = window.location;
globalThis.history = window.history;
globalThis.fetch = window.fetch;
globalThis.AbortController = window.AbortController ?? AbortController;
globalThis.IntersectionObserver = window.IntersectionObserver;

await import(pathToFileURL(resolve(webDir, 'js/main.js')).href);
await new Promise((r) => setTimeout(r, 80));

/* ------------------------------------------------------------------ 검증 */

const doc = window.document;
const failures = [];
const check = (name, ok, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${!ok && detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
};

const text = (sel) => doc.querySelector(sel)?.textContent?.trim() ?? '';
const cards = doc.querySelectorAll('#grid .card');
const chipLabels = (id) => [...doc.querySelectorAll(`#${id} .chip`)].map((c) => c.textContent.trim());

console.log('\nReverdi 프론트 부팅 스모크 (?cat=watch)');

check('부팅 중 처리되지 않은 예외 없음', errors.length === 0, errors[0]?.message);
check('URL 파라미터로 결과 화면 모드', doc.body.classList.contains('mode-list'));
check('매물 카드가 그려진다', cards.length >= 3, `카드 ${cards.length}장`);
check('카드가 원문 링크로 연결된다', cards[0]?.getAttribute('href') === 'https://ex.test/w1');
check('브랜드 태그가 영문으로 표기된다', text('#grid .tag-brand') === 'ROLEX', text('#grid .tag-brand'));
check('수집처 태그가 붙는다', text('#grid .tag-source') === '중고나라');

check('필터 제목이 카테고리를 따른다', text('#filterTitle') === '시계 상세 필터 검색', text('#filterTitle'));
check('카테고리 배지가 보인다', doc.getElementById('filterCatBadge')?.hidden === false);
check('브랜드 칩이 카테고리별로 채워진다',
  JSON.stringify(chipLabels('brandChips')) === JSON.stringify(['전체', 'ROLEX', 'OMEGA', 'CARTIER']),
  chipLabels('brandChips').join(','));
check('거래 플랫폼 칩이 채워진다',
  JSON.stringify(chipLabels('sourceChips')) === JSON.stringify(['전체', '당근마켓', '중고나라', '번개장터']),
  chipLabels('sourceChips').join(','));
check('정렬 칩 3종, 기본은 최저가순',
  chipLabels('sortChips').length === 3 && text('#sortChips .chip.on') === '최저가순');
check('가격 프리셋 6개', doc.querySelectorAll('#pricePresets .preset').length === 6);
check('프리셋 기본값은 전체', text('#pricePresets .preset.on') === '전체');

check('결과 제목에 총 건수', text('#resultTitle').includes('6'), text('#resultTitle'));
check('수집처 목록이 헤더에 표기', text('#resultSources').includes('중고나라'));
check('가격 통계 카드가 보인다', doc.getElementById('priceStats')?.hidden === false);
check('최저가 계산', text('#statMin') === '3,800,000원', text('#statMin'));
check('평균가 계산', text('#statAvg') === '10,266,667원', text('#statAvg'));
check('최고가 계산', text('#statMax') === '17,200,000원', text('#statMax'));

check('탭에서 시계가 활성', text('#catTabs .tab.on').includes('시계'));
check('대문 카테고리 카드 건수가 meta 값', text('#catGrid [data-category="watch"] .cat__foot') === '2개 매물',
  text('#catGrid [data-category="watch"] .cat__foot'));
check('추천 레일이 채워진다', doc.querySelectorAll('#recoGrid .card').length === 3);
check('서버에 category=watch 로 질의', calls.some((c) => c.includes('category=watch')));
check('서버에 order_by=price_asc 로 질의', calls.some((c) => c.includes('order_by=price_asc')));

// 무한 스크롤: sentinel(#pager)이 관찰 대상으로 등록되고, 교차 통보에
// 다음 장(offset=30)이 실제로 요청돼 카드가 누적되는지 본다.
check('#pager가 스크롤 sentinel로 등록된다', observed.some((n) => n?.id === 'pager'));
check('다음 장을 자동으로 요청한다', calls.some((c) => c.includes('offset=30')),
  calls.filter((c) => c.includes('offset')).join(' | '));
check('카드가 누적된다 (3 -> 6)', doc.querySelectorAll('#grid .card').length === 6,
  `${doc.querySelectorAll('#grid .card').length}장`);
check('더보기 버튼은 없다', doc.querySelector('.btn-more') === null);

console.log('');

if (failures.length) {
  console.error(`실패 ${failures.length}건:`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}

console.log('전부 통과.');
process.exit(0);
