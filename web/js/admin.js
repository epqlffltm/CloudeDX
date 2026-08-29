// web/js/admin.js
//
// 관리자 콘솔 — 화면 다섯 개를 해시 라우팅으로 전환한다.
//
//   #dashboard  상태 카드 + 매물 KPI
//   #api        /metrics(Prometheus) 파싱 — 가동 시간·누적 요청·오류·지연·스파크라인
//   #db         /ready 상세 — 읽기/쓰기 연결, 마이그레이션 리비전
//   #crawler    수집기 상태 + 최근 라운드 터미널 로그
//   #items      매물 분포 막대
//
// 별도 HTML 페이지로 쪼개지 않는 이유: 다섯 화면이 같은 데이터 로드(loadAll)를
// 공유한다. 페이지로 나누면 화면마다 같은 요청을 반복하고 코드도 다섯 벌이 된다.
//
// 화면의 모든 숫자는 실데이터다. 시안에 있던 "30일 가동률"이나 "Conn 42/100"처럼
// 뒷받침할 지표가 없는 값은 만들지 않았다 — 대신 지표에 실재하는 값(프로세스 시작
// 시각, 누적 요청 수, 오류 수, 평균 지연)으로 같은 자리를 채운다.

import { guard, renderAccountBar } from './auth.js';

const $ = (id) => document.getElementById(id);

const num = (n) => Number(n ?? 0).toLocaleString('ko-KR');

const esc = (s) =>
  String(s ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

/** ISO 시각 → "8/20 15:16" 정도로. 초까지는 이 화면에서 의미가 없다. */
function when(iso) {
  if (!iso) return '-';

  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';

  return d.toLocaleString('ko-KR', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function ago(iso) {
  if (!iso) return '수집 기록 없음';

  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff) || diff < 0) return '-';

  const min = Math.floor(diff / 60_000);
  if (min < 1) return '방금';
  if (min < 60) return `${min}분 전`;

  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;

  return `${Math.floor(hr / 24)}일 전`;
}

/** 초 → "3일 4시간" / "52분" 같은 가동 시간 표기. */
function durationText(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '-';

  const min = Math.floor(seconds / 60);
  if (min < 60) return `${min}분`;

  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 ${min % 60}분`;

  return `${Math.floor(hr / 24)}일 ${hr % 24}시간`;
}

/* ------------------------------------------------------------- 라우터 */

const ROUTES = ['dashboard', 'api', 'db', 'crawler', 'items', 'memo'];

function route() {
  const name = location.hash.replace('#', '');
  const view = ROUTES.includes(name) ? name : 'dashboard';

  for (const el of document.querySelectorAll('.view')) {
    el.hidden = el.dataset.view !== view;
  }

  for (const link of document.querySelectorAll('[data-nav]')) {
    link.classList.toggle('is-active', link.dataset.nav === view);
  }

  window.scrollTo({ top: 0 });
}

/* -------------------------------------------------------- 공용 fetch */

/**
 * fetch 하면서 걸린 시간을 같이 잰다. 실패해도 예외를 올리지 않고
 * {ok:false}로 돌려준다 — 카드 하나가 죽었다고 화면 전체가 멈추면 안 된다.
 */
async function timedFetch(url) {
  const t0 = performance.now();

  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    const ms = Math.round(performance.now() - t0);
    let body = null;

    try { body = await res.json(); } catch { /* 본문 없는 응답 */ }

    return { ok: res.ok, status: res.status, ms, body };
  } catch {
    return { ok: false, status: 0, ms: Math.round(performance.now() - t0), body: null };
  }
}

function card({ lead = false, label, dot = null, pulse = false, state, metaL = '', metaR = '' }) {
  return `
    <div class="scard${lead ? ' scard--lead' : ''}">
      <div class="scard__head">
        <span class="scard__label">${esc(label)}</span>
        ${dot ? `<span class="dot dot--${dot}${pulse ? ' dot--pulse' : ''}"></span>` : ''}
      </div>
      <p class="scard__state">${state}</p>
      <div class="scard__meta"><span>${esc(metaL)}</span><span>${esc(metaR)}</span></div>
    </div>`;
}

/* ------------------------------------------------- 대시보드: 상태 카드 */

function renderStatusCards(health, ready, crawler) {
  // 서버: 이 페이지가 응답을 받았다는 것 자체가 살아있다는 뜻이다.
  const server = health.ok
    ? card({ lead: true, label: 'FastAPI Server', dot: 'ok', pulse: true, state: '정상 작동', metaL: `응답 ${health.ms}ms` })
    : card({ lead: true, label: 'FastAPI Server', dot: 'bad', state: '응답 없음', metaL: '확인 실패' });

  // DB: /ready 는 준비 안 됐어도(503) 본문에 원인을 담아 준다. body 로 판단한다.
  const r = ready.body;
  let db;

  if (!r) {
    db = card({ label: 'PostgreSQL', dot: 'bad', state: '확인 실패', metaL: '/ready 응답 없음' });
  } else {
    const readOk = r.database?.connected;
    const writeOk = r.database_write?.connected;
    const migOk = r.migration?.up_to_date;

    const state = !readOk ? '읽기 장애' : !writeOk ? '쓰기 장애' : !migOk ? '스키마 구버전' : '안정적';
    const dot = !readOk ? 'bad' : (!writeOk || !migOk) ? 'warn' : 'ok';

    db = card({
      label: 'PostgreSQL', dot, state,
      metaL: `읽기 ${readOk ? 'OK' : '실패'} · 쓰기 ${writeOk ? 'OK' : '실패'}`,
      metaR: `${migOk ? '스키마 최신' : '마이그레이션 필요'} · ${ready.ms}ms`,
    });
  }

  // 크롤러: overview 가 판정해 준 값을 그대로 쓴다.
  let bot;

  if (!crawler) {
    bot = card({ label: '데이터 크롤러', dot: 'bad', state: '확인 실패' });
  } else if (crawler.stale) {
    bot = card({ label: '데이터 크롤러', dot: 'warn', state: '응답 없음', metaL: '수집 기록이 오래됨', metaR: `최근 수집 ${ago(crawler.last_crawled_at)}` });
  } else if (crawler.is_running) {
    bot = card({ label: '데이터 크롤러', dot: 'good', pulse: true, state: '수집 중', metaL: `주기 ${num(crawler.interval_minutes)}분`, metaR: `최근 수집 ${ago(crawler.last_crawled_at)}` });
  } else {
    bot = card({ label: '데이터 크롤러', dot: 'ok', state: '대기 중', metaL: `주기 ${num(crawler.interval_minutes)}분`, metaR: `최근 수집 ${ago(crawler.last_crawled_at)}` });
  }

  $('statusGrid').innerHTML = server + db + bot;
}

function renderKpi(items) {
  const cards = [
    { label: '노출 중인 매물', value: items.visible, hint: '활성 + 정제 통과' },
    { label: '전체 적재', value: items.stored, hint: 'items 테이블 총 행 수' },
    { label: '비활성', value: items.inactive, hint: '판매완료 · 연속 미발견' },
    { label: '정제 제외', value: items.unusable, hint: '대상 외 상품으로 판정' },
  ];

  $('kpiGrid').innerHTML = cards
    .map(
      (c) => `
      <div class="kpi">
        <div class="kpi__label">${esc(c.label)}</div>
        <div class="kpi__value">${num(c.value)}</div>
        <div class="kpi__hint">${esc(c.hint)}</div>
      </div>`,
    )
    .join('');
}

/* ------------------------------------------------ API 뷰: /metrics 파싱 */

function parseLabels(raw) {
  const labels = {};

  for (const m of raw.matchAll(/(\w+)="((?:[^"\\]|\\.)*)"/g)) {
    labels[m[1]] = m[2].replaceAll('\\"', '"');
  }

  return labels;
}

/**
 * /metrics 텍스트를 파싱한다.
 *
 * 쓰는 지표 (prometheus-fastapi-instrumentator + prometheus_client 기본):
 *   http_requests_total{handler,method,status}          누적 요청 수
 *   http_request_duration_seconds_sum/_count{handler}   평균 지연 계산용
 *   process_start_time_seconds                          프로세스 시작 시각(가동 시간)
 */
function parseMetrics(text) {
  const requests = new Map(); // "handler|method" -> { handler, method, total, errors }
  const durations = new Map(); // handler -> { sum, count }
  let startTime = null;

  for (const line of text.split('\n')) {
    if (!line || line.startsWith('#')) continue;

    // 라벨 없는 지표 (process_start_time_seconds 1.756e+09)
    const plain = line.match(/^(\w+)\s+([0-9.eE+-]+)$/);

    if (plain) {
      if (plain[1] === 'process_start_time_seconds') startTime = Number(plain[2]);
      continue;
    }

    const m = line.match(/^(\w+)\{([^}]*)\}\s+([0-9.eE+-]+)/);
    if (!m) continue;

    const [, name, rawLabels, rawValue] = m;
    const value = Number(rawValue);
    if (!Number.isFinite(value)) continue;

    if (name === 'http_requests_total') {
      const { handler = '?', method = '?', status = '' } = parseLabels(rawLabels);
      if (handler === 'none') continue; // 라우트에 매칭 안 된 요청(404 등)

      const key = `${handler}|${method}`;
      const row = requests.get(key) ?? { handler, method, total: 0, errors: 0 };

      row.total += value;
      // instrumentator 는 status 를 "2xx" 형태로 묶어 준다. 2xx/3xx 외는 오류로 센다.
      if (status && !status.startsWith('2') && !status.startsWith('3')) row.errors += value;

      requests.set(key, row);
    } else if (name === 'http_request_duration_seconds_sum' || name === 'http_request_duration_seconds_count') {
      const { handler = '?' } = parseLabels(rawLabels);
      if (handler === 'none') continue;

      const d = durations.get(handler) ?? { sum: 0, count: 0 };
      if (name.endsWith('_sum')) d.sum += value; else d.count += value;
      durations.set(handler, d);
    }
  }

  const rows = [...requests.values()]
    .sort((a, b) => b.total - a.total)
    .map((row) => {
      const d = durations.get(row.handler);
      return { ...row, avgMs: d && d.count > 0 ? (d.sum / d.count) * 1000 : null };
    });

  return { rows, durations, startTime };
}

// 스파크라인용 이력. 화면을 열어 둔 동안 10초마다 "그 사이 늘어난 요청 수"를
// 기록한다 — 서버에는 시계열 저장소가 없으므로, 브라우저가 보는 동안만이라도
// 흐름을 실측으로 그린다. 새로고침하면 비워지는 것이 정직한 동작이다.
const SPARK_POINTS = 14;
const sparkHistory = new Map(); // "handler|method" -> number[]
let lastTotals = null; // Map "handler|method" -> total

function updateSparkHistory(rows) {
  const totals = new Map(rows.map((r) => [`${r.handler}|${r.method}`, r.total]));

  if (lastTotals) {
    for (const [key, total] of totals) {
      const delta = Math.max(0, total - (lastTotals.get(key) ?? total));
      const hist = sparkHistory.get(key) ?? [];

      hist.push(delta);
      if (hist.length > SPARK_POINTS) hist.shift();
      sparkHistory.set(key, hist);
    }
  }

  lastTotals = totals;
}

function sparkHtml(key) {
  const hist = sparkHistory.get(key) ?? [];

  if (hist.length < 2) return '<span class="spark--empty">수집 중…</span>';

  const max = Math.max(...hist, 1);

  return `<span class="spark" aria-hidden="true">${hist
    .map((v, i) => `<i${i === hist.length - 1 ? ' class="hot"' : ''} style="height:${Math.max(9, (v / max) * 100)}%"></i>`)
    .join('')}</span>`;
}

function renderApiCards(parsed) {
  const totalReq = parsed.rows.reduce((s, r) => s + r.total, 0);
  const totalErr = parsed.rows.reduce((s, r) => s + r.errors, 0);

  let sum = 0;
  let count = 0;

  for (const d of parsed.durations.values()) { sum += d.sum; count += d.count; }

  const uptime = parsed.startTime
    ? durationText(Date.now() / 1000 - parsed.startTime)
    : '-';

  $('apiCards').innerHTML = [
    card({ lead: true, label: '서버 가동 시간', state: esc(uptime), metaL: 'process_start_time 기준' }),
    card({ label: '누적 요청', state: num(totalReq), metaL: '기동 이후 전체' }),
    card({
      label: '오류 응답', dot: totalErr > 0 ? 'warn' : 'ok',
      state: num(totalErr), metaL: '4xx · 5xx 합계',
    }),
    card({
      label: '평균 지연',
      state: count > 0 ? `${((sum / count) * 1000).toFixed(1)}<span style="font-size:15px">ms</span>` : '-',
      metaL: '전체 요청 평균',
    }),
  ].join('');
}

function renderApiTable(rows) {
  const table = $('apiTable');

  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="table__empty">
      아직 집계된 요청이 없거나 /metrics 를 읽을 수 없습니다.
    </td></tr></tbody>`;
    return;
  }

  table.innerHTML = `
    <thead><tr>
      <th>Endpoint</th><th>Method</th><th>Status</th>
      <th class="num">Avg Latency</th><th>Traffic</th><th class="num">누적 요청</th>
    </tr></thead>
    <tbody>
      ${rows.slice(0, 12).map((r) => `
        <tr>
          <td class="path">${esc(r.handler)}</td>
          <td><span class="method-badge">${esc(r.method)}</span></td>
          <td>${r.errors > 0
            ? `<span class="st st--bad"><span class="dot dot--bad"></span>오류 ${num(r.errors)}건</span>`
            : '<span class="st st--ok"><span class="dot dot--ok"></span>정상</span>'}</td>
          <td class="num">${r.avgMs == null ? '-' : `${r.avgMs.toFixed(1)}ms`}</td>
          <td>${sparkHtml(`${r.handler}|${r.method}`)}</td>
          <td class="num">${num(r.total)}</td>
        </tr>`).join('')}
    </tbody>`;
}

async function loadMetrics() {
  try {
    const res = await fetch('/metrics', { credentials: 'same-origin' });
    if (!res.ok) throw new Error();

    const parsed = parseMetrics(await res.text());

    updateSparkHistory(parsed.rows);
    renderApiCards(parsed);
    renderApiTable(parsed.rows);
  } catch {
    renderApiTable([]);
  }
}

/* ------------------------------------------------------------- DB 뷰 */

function renderDb(ready, items) {
  const r = ready.body;
  const cardsBox = $('dbCards');
  const facts = $('dbFacts');

  if (!r) {
    cardsBox.innerHTML = card({ label: 'PostgreSQL', dot: 'bad', state: '확인 실패', metaL: '/ready 응답 없음' });
    facts.innerHTML = '';
    return;
  }

  const readOk = r.database?.connected;
  const writeOk = r.database_write?.connected;
  const migOk = r.migration?.up_to_date;

  cardsBox.innerHTML = [
    card({
      lead: true, label: '읽기 경로', dot: readOk ? 'ok' : 'bad',
      state: readOk ? '연결됨' : '연결 실패',
      metaL: '조회 트래픽이 쓰는 경로', metaR: `${ready.ms}ms`,
    }),
    card({
      label: '쓰기 경로', dot: writeOk ? 'ok' : 'warn',
      state: writeOk ? '연결됨' : '연결 실패',
      metaL: '업로드·크롤러가 쓰는 경로',
    }),
    card({
      label: '스키마', dot: migOk ? 'ok' : 'warn',
      state: migOk ? '최신' : '구버전',
      metaL: migOk ? '마이그레이션 반영됨' : 'alembic upgrade 필요',
    }),
  ].join('');

  const rev = (v) => (v ? `<code>${esc(String(v).slice(0, 12))}</code>` : '-');

  facts.innerHTML = `
    <dt>읽기 연결</dt><dd>${readOk ? '정상' : `실패 (${esc(r.database?.error ?? '?')})`}</dd>
    <dt>쓰기 연결</dt><dd>${writeOk ? '정상' : `실패 (${esc(r.database_write?.error ?? '?')})`}</dd>
    <dt>현재 리비전</dt><dd>${rev(r.migration?.current)}</dd>
    <dt>최신 리비전</dt><dd>${rev(r.migration?.head ?? r.migration?.heads?.[0])}</dd>
    <dt>적재 행 수</dt><dd>${items ? `${num(items.stored)} 행 (items 테이블)` : '-'}</dd>
    <dt>/ready 판정</dt><dd>${r.ready ? 'Ready — 트래픽 수용 가능' : 'NotReady — 로드밸런서에서 제외됨'}</dd>`;
}

/* --------------------------------------------------------- 크롤러 뷰 */

function renderCrawler(crawler) {
  const box = $('crawlerCards');

  if (!crawler) {
    box.innerHTML = card({ label: '데이터 크롤러', dot: 'bad', state: '확인 실패' });
    return;
  }

  const status = crawler.stale
    ? { dot: 'warn', text: '응답 없음', hint: '수집 기록이 오래됨' }
    : crawler.is_running
      ? { dot: 'good', text: '수집 중', hint: '이번 라운드 진행 중', pulse: true }
      : { dot: 'ok', text: '대기 중', hint: '다음 라운드 대기' };

  box.innerHTML = [
    card({
      lead: true, label: '상태', dot: status.dot, pulse: !!status.pulse,
      state: status.text, metaL: status.hint, metaR: `최근 수집 ${ago(crawler.last_crawled_at)}`,
    }),
    card({
      label: '완료 라운드', state: num(crawler.rounds_completed),
      metaL: '성공으로 끝난 수집 횟수',
    }),
    card({
      label: '수집 설정', state: `${num(crawler.interval_minutes)}<span style="font-size:15px">분 주기</span>`,
      metaL: `미발견 ${num(crawler.missing_threshold)}회 연속이면 비활성`,
    }),
  ].join('');
}

function runLine(r) {
  const started = when(r.started_at);

  if (r.status === 'failed') {
    return `
      <div class="term__row">
        <span class="term__time">[${esc(started)}]</span>
        <span class="term__tag term__tag--err">ERROR:</span>
        <span>수집 라운드 #${esc(r.id)} 실패 — ${esc(r.error || '원인 미기록')}</span>
      </div>`;
  }

  if (r.status === 'running') {
    return `
      <div class="term__row">
        <span class="term__time">[${esc(started)}]</span>
        <span class="term__tag term__tag--warn">RUN :</span>
        <span>수집 라운드 #${esc(r.id)} 진행 중…</span>
      </div>`;
  }

  const secs = r.finished_at && r.started_at
    ? Math.max(0, Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000))
    : null;

  return `
    <div class="term__row">
      <span class="term__time">[${esc(started)}]</span>
      <span class="term__tag term__tag--info">INFO:</span>
      <span>수집 라운드 #${esc(r.id)} 완료 — ${r.item_count == null ? '?' : num(r.item_count)}건 저장${secs == null ? '' : ` (${num(secs)}s)`}</span>
    </div>`;
}

function renderCrawlLog(runs) {
  const box = $('crawlLog');

  if (!runs.length) {
    box.innerHTML = '<p class="term__empty">수집 이력이 없습니다. 크롤러가 첫 라운드를 돌면 여기에 쌓입니다.</p>';
    return;
  }

  // 로그는 시간순(오래된 것부터)으로 읽는 물건이다. API 는 최신순으로 주므로 뒤집는다.
  box.innerHTML = [...runs].reverse().map(runLine).join('');
  box.scrollTop = box.scrollHeight; // 최신 줄이 보이게
}

/* ----------------------------------------------------------- 분포 막대 */

function renderBars(containerId, data, { limit = 12 } = {}) {
  const box = $(containerId);
  if (!box) return;

  const rows = Object.entries(data ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);

  if (!rows.length) {
    box.innerHTML = `<p class="bars__empty">해당 없음</p>`;
    return;
  }

  const max = rows[0][1];

  box.innerHTML = rows
    .map(
      ([key, n]) => `
      <div class="bar">
        <span class="bar__label" title="${esc(key)}">${esc(key)}</span>
        <span class="bar__track"><span class="bar__fill" style="width:${(n / max) * 100}%"></span></span>
        <span class="bar__value">${num(n)}</span>
      </div>`,
    )
    .join('');
}

/* -------------------------------------------------------------- 메모 뷰 */
//
// 관리자 공용 메모 (GET/PUT /api/admin/memo — 서버가 텍스트 파일 한 장으로 저장).
// dirty 플래그가 핵심이다: 입력 중일 때 새로고침(loadAll)이 돌아도 쓰고 있던
// 내용을 서버 값으로 덮어쓰지 않는다.

let memoDirty = false;

function memoStatus(text, cls = '') {
  const el = $('memoStatus');
  el.textContent = text;
  el.className = `memo-status${cls ? ` memo-status--${cls}` : ''}`;
}

async function loadMemo() {
  if (memoDirty) return; // 입력 중이면 서버 값으로 덮지 않는다

  try {
    const res = await fetch('/api/admin/memo', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(String(res.status));

    const data = await res.json();

    $('memoText').value = data.text;
    memoStatus(data.updated_at ? `마지막 저장 ${when(data.updated_at)}` : '아직 저장된 메모가 없습니다');
  } catch {
    memoStatus('메모를 불러오지 못했습니다.', 'error');
  }
}

async function saveMemo() {
  const btn = $('memoSave');
  btn.disabled = true;

  try {
    const res = await fetch('/api/admin/memo', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: $('memoText').value,
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) throw new Error(data.detail || `서버가 ${res.status}로 응답했습니다.`);

    memoDirty = false;
    memoStatus(`저장됨 · ${when(data.updated_at)}`);
  } catch (err) {
    memoStatus(`저장 실패: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ 로드 */

async function loadAll() {
  const btn = $('refreshBtn');
  btn.disabled = true;

  try {
    // 서로 독립인 요청은 한꺼번에 보낸다. 순서대로 기다리면 지연이 합산된다.
    const [overviewRes, health, ready] = await Promise.all([
      fetch('/api/admin/overview', { credentials: 'same-origin' }),
      timedFetch('/health'),
      timedFetch('/ready'),
      loadMetrics(), // 결과는 자기 화면(#api)에 직접 그린다
    ]);

    if (overviewRes.status === 401 || overviewRes.status === 403) {
      // 세션 만료. 옛 숫자를 남겨두면 지금 상태로 오해하므로 바로 보낸다.
      location.replace('login.html');
      return;
    }

    if (!overviewRes.ok) throw new Error(`서버가 ${overviewRes.status}로 응답했습니다.`);

    const data = await overviewRes.json();

    loadMemo(); // 결과는 자기 화면(#memo)에 직접 그린다

    renderStatusCards(health, ready, data.crawler);
    renderKpi(data.items);
    renderDb(ready, data.items);
    renderCrawler(data.crawler);
    renderCrawlLog(data.crawler.recent_runs ?? []);
    renderBars('bySource', data.items.by_source);
    renderBars('byCategory', data.items.by_category);
    renderBars('byBrand', data.items.by_brand);
    renderBars('byReject', data.items.reject_reasons);
    renderBars('byUnavailable', data.items.unavailable_reasons);

    $('errorBox').hidden = true;
  } catch (err) {
    const box = $('errorBox');
    box.textContent = `현황을 불러오지 못했습니다: ${err.message}`;
    box.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

async function init() {
  const me = await guard('admin');
  if (!me) return; // guard가 이미 다른 페이지로 보냈다

  renderAccountBar(me);

  window.addEventListener('hashchange', route);
  route();

  $('refreshBtn').addEventListener('click', loadAll);

  // 메모: 저장 버튼 + Ctrl/⌘+S. 입력이 시작되면 dirty 표시로 알려준다.
  $('memoSave').addEventListener('click', saveMemo);
  $('memoText').addEventListener('input', () => {
    memoDirty = true;
    memoStatus('저장되지 않은 변경이 있습니다', 'dirty');
  });
  $('memoText').addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      saveMemo();
    }
  });

  await loadAll();

  // 스파크라인용 지표 폴링. 10초면 지표 응답(수 KB)에 비해 부담이 없고,
  // 화면을 열어 둔 사람에게 "지금 트래픽이 흐르는가"를 보여주기엔 충분하다.
  setInterval(loadMetrics, 10_000);
}

init();
