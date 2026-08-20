// web/js/client.js
//
// 기업고객 CSV 업로드 화면.
//
// 파일을 multipart가 아니라 본문(text/csv)으로 그대로 보낸다. 서버가 python-multipart
// 없이 받도록 맞춘 것이다(app/routers/uploads.py 참고). 보낼 필드가 파일 하나뿐이라
// multipart로 감쌀 이유가 없다.

import { guard, renderAccountBar } from './auth.js';

const $ = (id) => document.getElementById(id);

const num = (n) => Number(n ?? 0).toLocaleString('ko-KR');

const esc = (s) =>
  String(s ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

const MAX_BYTES = 5 * 1024 * 1024;

let selected = null;

function showError(message) {
  const box = $('errorBox');
  box.textContent = message;
  box.hidden = false;
}

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

  // 저장은 됐는데 목록에 안 뜨는 경우. 사용자가 제일 헷갈리는 지점이라
  // 이유와 고칠 방법까지 같이 적는다.
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

async function upload() {
  if (!selected) return;

  const btn = $('uploadBtn');
  btn.disabled = true;
  btn.textContent = '업로드 중…';
  $('errorBox').hidden = true;

  try {
    // 텍스트로 읽어 보낸다. 인코딩 판정(UTF-8/CP949)은 서버가 바이트를 보고 한다.
    const body = await selected.arrayBuffer();

    const res = await fetch('/api/uploads/csv', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'text/csv' },
      body,
    });

    if (res.status === 401 || res.status === 403) {
      location.replace('login.html');
      return;
    }

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw new Error(data.detail || `서버가 ${res.status}로 응답했습니다.`);
    }

    renderResult(data);
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
    'title,price,url,brand,image_url,region',
    '샤넬 클래식 미디움 캐비어 은장,980만원,https://example.com/items/1,샤넬,,서울 강남구',
    '롤렉스 서브마리너 124060,17200000,https://example.com/items/2,롤렉스,,부산 해운대구',
    '루이비통 온더고 MM,"2,450,000",https://example.com/items/3,,,경기 성남시',
  ];

  // BOM을 붙인다. 엑셀이 UTF-8 CSV를 BOM 없이 열면 한글이 깨진다.
  const blob = new Blob(['\ufeff' + rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: 'reverdi-sample.csv' });

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

  // 브라우저 창 아무 데나 파일을 떨어뜨렸을 때 그 파일로 페이지가 이동하는
  // 기본 동작을 막는다. 올리려다 놓친 파일 때문에 화면이 날아가면 안 된다.
  for (const type of ['dragover', 'drop']) {
    window.addEventListener(type, (e) => {
      if (!drop.contains(e.target)) e.preventDefault();
    });
  }
}

async function init() {
  const me = await guard('client');
  if (!me) return;

  renderAccountBar(me);
  wireDropZone();

  $('pickBtn').addEventListener('click', () => $('fileInput').click());
  $('fileInput').addEventListener('change', (e) => selectFile(e.target.files?.[0]));
  $('uploadBtn').addEventListener('click', upload);
  $('sampleBtn').addEventListener('click', downloadSample);
}

init();
