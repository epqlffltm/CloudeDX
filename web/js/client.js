// web/js/client.js
//
// 기업고객 포털 — 화면 셋을 해시 라우팅으로 전환한다.
//
//   #inventory  내 매물 목록 + 사진 등록 (client_photos.js 담당)
//   #register   단건 등록 폼
//   #bulk       CSV 일괄 업로드
//
// 단건 등록에 전용 API 는 없다. 폼 입력을 **1행짜리 CSV 로 만들어**
// 기존 /api/uploads/csv 로 보낸다 — 저장 경로가 하나라서 제목 정제·브랜드
// 판정·url 중복 처리 규칙이 일괄 등록과 완전히 같아진다. 백엔드에 단건
// 엔드포인트를 새로 파면 그 규칙이 두 벌이 된다.
//
// 매물이 바뀌는 동작(등록·업로드)이 성공하면 'reverdi:items-changed' 이벤트를
// 쏜다. 목록 화면(client_photos.js)은 그 이벤트만 듣고 다시 불러온다 —
// 두 파일이 서로의 함수를 직접 부르지 않아도 된다.

import { guard, renderAccountBar } from './auth.js';

const $ = (id) => document.getElementById(id);

const num = (n) => Number(n ?? 0).toLocaleString('ko-KR');

const esc = (s) =>
  String(s ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

const MAX_BYTES = 5 * 1024 * 1024;

const itemsChanged = () => window.dispatchEvent(new CustomEvent('reverdi:items-changed'));

function showError(message) {
  const box = $('errorBox');
  box.textContent = message;
  box.hidden = false;
}

/* ------------------------------------------------------------- 라우터 */

const ROUTES = ['inventory', 'register', 'bulk'];

function route() {
  const name = location.hash.replace('#', '');
  const view = ROUTES.includes(name) ? name : 'inventory';

  for (const el of document.querySelectorAll('.view')) {
    el.hidden = el.dataset.view !== view;
  }

  for (const link of document.querySelectorAll('[data-nav]')) {
    link.classList.toggle('is-active', link.dataset.nav === view);
  }

  window.scrollTo({ top: 0 });
}

/* ------------------------------------------------------- CSV 공용 유틸 */

/** CSV 셀 하나. 쉼표·따옴표·줄바꿈이 들어오면 규격대로 감싼다. */
function csvCell(value) {
  const s = String(value ?? '');

  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

/** CSV 본문을 서버로 보낸다. 단건 등록과 파일 업로드가 같은 문을 쓴다. */
async function postCsv(text) {
  const res = await fetch('/api/uploads/csv', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'text/csv' },
    body: text,
  });

  if (res.status === 401 || res.status === 403) {
    location.replace('login.html');
    throw new Error('세션이 만료되었습니다.');
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.detail || `서버가 ${res.status}로 응답했습니다.`);
  }

  return data;
}

/* ------------------------------------------------------- 단건 등록 폼 */

function regResult(kind, title, body) {
  const box = $('regResult');

  box.className = `reg-result reg-result--${kind}`;
  box.innerHTML = `<strong>${esc(title)}</strong>${esc(body)}`;
  box.hidden = false;
}

async function submitRegister(e) {
  e.preventDefault();

  const title = $('regTitle').value.trim();
  const price = $('regPrice').value.trim();
  const url = $('regUrl').value.trim();

  if (!title || !price || !url) {
    regResult('bad', '필수 항목이 비었습니다', '제목·가격·상품 링크는 반드시 입력해야 합니다.');
    return;
  }

  const btn = $('regSubmit');
  btn.disabled = true;
  btn.textContent = '등록 중…';

  // 폼 → 1행 CSV. 서버의 헤더 별칭·가격 파서·수식 무력화가 그대로 적용된다.
  const csv = [
    'title,price,url,brand,image_url,region,is_authenticated',
    [
      title, price, url,
      $('regBrand').value.trim(),
      $('regImage').value.trim(),
      $('regRegion').value.trim(),
      $('regAuth').checked ? 'true' : '',
    ].map(csvCell).join(','),
  ].join('\r\n');

  try {
    const data = await postCsv(csv);

    if (data.visible > 0) {
      regResult('ok', '등록 완료', '검색 목록에 바로 노출됩니다. 사진 파일은 \'내 매물\'에서 올릴 수 있습니다.');
      // 다음 건 입력이 편하게 식별 정보만 비운다. 브랜드·지역은 이어서 쓰는 값이라 남긴다.
      $('regTitle').value = '';
      $('regPrice').value = '';
      $('regUrl').value = '';
      $('regImage').value = '';
      $('regAuth').checked = false;
      itemsChanged();
    } else if (data.saved > 0) {
      // 저장은 됐는데 정제에서 걸러진 경우 — 사용자가 제일 헷갈리는 지점.
      regResult('warn', '저장됐지만 목록에는 아직 안 뜹니다',
        '제목에서 브랜드나 카테고리를 판정하지 못했습니다. 제목에 브랜드명과 품목(가방·시계 등)을 함께 넣어 같은 링크로 다시 등록하면 갱신되며 노출됩니다.');
      itemsChanged();
    } else {
      regResult('bad', '등록되지 않았습니다', (data.errors ?? [])[0] ?? '입력값을 확인해 주세요.');
    }
  } catch (err) {
    regResult('bad', '등록에 실패했습니다', err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '매물 등록 →';
  }
}

function clearRegister() {
  for (const id of ['regTitle', 'regPrice', 'regUrl', 'regBrand', 'regImage', 'regRegion']) {
    $(id).value = '';
  }
  $('regAuth').checked = false;
  $('regResult').hidden = true;
}

/* -------------------------------------------------------- CSV 업로드 */

let selected = null;

/** 파일 하나를 고른 상태로 만든다. 버튼 선택과 드래그가 같은 문을 쓴다. */
function selectFile(file) {
  $('errorBox').hidden = true;

  if (!file) return;

  if (!/\.csv$/i.test(file.name) && file.type !== 'text/csv') {
    showError('CSV 파일만 올릴 수 있습니다.');
    return;
  }

  if (file.size > MAX_BYTES) {
    showError(`파일이 너무 큽니다. 최대 5MB까지 가능합니다. (${(file.size / 1024 / 1024).toFixed(1)}MB)`);
    return;
  }

  selected = file;

  const name = $('fileName');
  name.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  name.hidden = false;

  $('uploadBtn').disabled = false;
}

function renderResult(data) {
  $('resultKpi').innerHTML = [
    { label: '읽은 행', value: data.total_rows },
    { label: '저장됨', value: data.saved },
    { label: '목록 노출', value: data.visible },
    { label: '제외됨', value: data.skipped },
  ]
    .map(
      (c) => `
      <div class="kpi">
        <div class="kpi__label">${esc(c.label)}</div>
        <div class="kpi__value">${num(c.value)}</div>
      </div>`,
    )
    .join('');

  const errors = data.errors ?? [];
  const filtered = data.filtered ?? [];
  let html = '';

  if (errors.length) {
    html += `<details class="errors" open>
       <summary>형식 오류로 제외된 행 ${num(errors.length)}건${data.skipped > errors.length ? ` (전체 ${num(data.skipped)}건 중 앞부분)` : ''}</summary>
       <ul>${errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>
     </details>`;
  }

  // 저장은 됐는데 목록에 안 뜨는 경우 — 이유와 고칠 방법까지 같이 적는다.
  if (filtered.length) {
    html += `<details class="errors" open>
       <summary>저장됐지만 목록에 안 뜨는 매물 ${num(filtered.length)}건</summary>
       <p class="panel__note" style="margin-top:8px">
         제목에서 브랜드나 카테고리를 판정하지 못해 정제 단계에서 제외됐습니다.
         제목에 브랜드명과 품목(가방 · 시계 등)을 함께 넣으면 노출됩니다.
       </p>
       <ul>${filtered.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
     </details>`;
  }

  $('resultErrors').innerHTML = html;

  $('resultPanel').hidden = false;
  $('resultPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// 이번 세션 업로드 기록. 서버가 이력을 저장하지 않으므로 이 배열이 전부이고,
// 새로고침하면 사라지는 것이 정직한 동작이다 — 화면에도 그렇게 적어 두었다.
const history = [];

function renderHistory() {
  $('histRows').innerHTML = history.length
    ? history
      .map(
        (h) => `
        <tr>
          <td>${esc(h.name)}</td>
          <td>${esc(h.at)}</td>
          <td class="num">${num(h.total_rows)}</td>
          <td class="num">${num(h.saved)}</td>
          <td class="num">${num(h.visible)}</td>
          <td class="num">${num(h.skipped)}</td>
        </tr>`,
      )
      .join('')
    : '<tr><td colspan="6" class="hist-empty">아직 이 세션에서 올린 파일이 없습니다.</td></tr>';
}

async function upload() {
  if (!selected) return;

  const btn = $('uploadBtn');
  btn.disabled = true;
  btn.textContent = '업로드 중…';
  $('errorBox').hidden = true;

  try {
    // 바이트 그대로 보낸다. 인코딩 판정(UTF-8/CP949)은 서버가 한다.
    const data = await postCsv(await selected.arrayBuffer());

    renderResult(data);

    history.unshift({
      name: selected.name,
      at: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
      ...data,
    });
    renderHistory();

    if (data.saved > 0) itemsChanged();
  } catch (err) {
    showError(`업로드에 실패했습니다: ${err.message}`);
  } finally {
    btn.disabled = !selected;
    btn.textContent = '업로드';
  }
}

/** 예시 CSV. 형식을 글로 설명하는 것보다 파일 하나를 주는 편이 빠르다. */
function downloadSample() {
  const rows = [
    'title,price,url,brand,image_url,region,is_authenticated',
    '샤넬 클래식 미디움 캐비어 은장 가방,980만원,https://example.com/items/1,샤넬,,서울 강남구,true',
    '롤렉스 서브마리너 124060 시계,17200000,https://example.com/items/2,롤렉스,,부산 해운대구,',
    '루이비통 온더고 MM 토트백,"2,450,000",https://example.com/items/3,,,경기 성남시,',
  ];

  // BOM을 붙인다. 엑셀이 UTF-8 CSV를 BOM 없이 열면 한글이 깨진다.
  const blob = new Blob(['\ufeff' + rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: 'reverdi-template.csv' });

  a.click();
  URL.revokeObjectURL(url);
}

function wireDropZone() {
  const drop = $('drop');

  for (const type of ['dragenter', 'dragover']) {
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.add('drop--over');
    });
  }

  for (const type of ['dragleave', 'drop']) {
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.remove('drop--over');
    });
  }

  drop.addEventListener('drop', (e) => selectFile(e.dataTransfer?.files?.[0]));

  // 브라우저 창 아무 데나 파일을 떨어뜨렸을 때 페이지가 이동하는 기본 동작을 막는다.
  for (const type of ['dragover', 'drop']) {
    window.addEventListener(type, (e) => {
      if (!drop.contains(e.target)) e.preventDefault();
    });
  }
}

/* ------------------------------------------------------------------ 부팅 */

async function init() {
  const me = await guard('client');
  if (!me) return; // guard가 이미 다른 페이지로 보냈다

  renderAccountBar(me);

  window.addEventListener('hashchange', route);
  route();

  // CSV 업로드
  wireDropZone();
  $('pickBtn').addEventListener('click', () => $('fileInput').click());
  $('fileInput').addEventListener('change', (e) => selectFile(e.target.files?.[0]));
  $('uploadBtn').addEventListener('click', upload);
  $('sampleBtn').addEventListener('click', downloadSample);

  // 단건 등록
  $('regForm').addEventListener('submit', submitRegister);
  $('regClear').addEventListener('click', clearRegister);
}

init();
