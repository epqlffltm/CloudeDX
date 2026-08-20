// web/js/admin.js
//
// 관리자 대시보드. /api/admin/overview 응답 하나로 전부 그린다.

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

/* ---------------------------------------------------------------- 그리기 */

function renderKpi(items) {
  // 노출/적재를 나란히 둔 이유: 둘의 차이가 곧 필터링된 양이고,
  // 그 비율이 튀면 정제 규칙이나 수집 품질을 봐야 한다는 신호다.
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

function renderCrawler(crawler) {
  const status = crawler.stale
    ? { cls: 'warn', text: '응답 없음 (기록이 오래됨)' }
    : crawler.is_running
      ? { cls: 'ok', text: '수집 중' }
      : { cls: 'idle', text: '대기 중' };

  $('crawlerInfo').innerHTML = `
    <div class="kv__row"><span>상태</span><b><span class="dot dot--${status.cls}"></span>${esc(status.text)}</b></div>
    <div class="kv__row"><span>마지막 수집</span><b>${esc(ago(crawler.last_crawled_at))}</b></div>
    <div class="kv__row"><span>완료 라운드</span><b>${num(crawler.rounds_completed)}회</b></div>
    <div class="kv__row"><span>수집 주기</span><b>${num(crawler.interval_minutes)}분</b></div>
    <div class="kv__row"><span>미발견 임계값</span><b>${num(crawler.missing_threshold)}회 연속</b></div>`;
}

function renderRuns(runs) {
  if (!runs.length) {
    $('runsTable').innerHTML = `<tbody><tr><td class="table__empty">수집 이력이 없습니다</td></tr></tbody>`;
    return;
  }

  const label = { success: '성공', running: '진행 중', failed: '실패' };
  const cls = { success: 'ok', running: 'idle', failed: 'bad' };

  $('runsTable').innerHTML = `
    <thead><tr><th>시작</th><th>종료</th><th>상태</th><th class="num">수집</th><th>비고</th></tr></thead>
    <tbody>
      ${runs
        .map(
          (r) => `
        <tr>
          <td>${esc(when(r.started_at))}</td>
          <td>${esc(when(r.finished_at))}</td>
          <td><span class="dot dot--${cls[r.status] ?? 'idle'}"></span>${esc(label[r.status] ?? r.status)}</td>
          <td class="num">${r.item_count == null ? '-' : num(r.item_count)}</td>
          <td class="table__note" title="${esc(r.error ?? '')}">${esc(r.error ?? '')}</td>
        </tr>`,
        )
        .join('')}
    </tbody>`;
}

/**
 * 막대 목록. 최댓값을 100%로 잡는 상대 막대라 절대 규모는 숫자로만 읽힌다 —
 * 여기서 보려는 건 "어디에 쏠려 있나"이지 총량이 아니다.
 */
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

/* ------------------------------------------------------------------ 로드 */

async function loadOverview() {
  const btn = $('refreshBtn');
  btn.disabled = true;

  try {
    const res = await fetch('/api/admin/overview', { credentials: 'same-origin' });

    if (res.status === 401 || res.status === 403) {
      // 세션이 만료됐거나 권한이 사라졌다. 화면에 옛 숫자를 남겨두면
      // 지금 상태로 오해하므로 바로 로그인으로 보낸다.
      location.replace('login.html');
      return;
    }

    if (!res.ok) throw new Error(`서버가 ${res.status}로 응답했습니다.`);

    const data = await res.json();

    renderKpi(data.items);
    renderCrawler(data.crawler);
    renderRuns(data.crawler.recent_runs ?? []);
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
  $('refreshBtn').addEventListener('click', loadOverview);
  await loadOverview();
}

init();
