// web/js/client_photos.js
//
// '내 매물' 화면 — 직접등록 매물 목록, 검색, 페이지, CSV 내보내기, 사진 등록.
//
// client.js 와 별도 파일인 이유는 두 쪽이 서로를 몰라도 되기 때문이다. 등록/업로드
// (client.js)가 끝나면 'reverdi:items-changed' 이벤트만 쏘고, 이 파일은 그 이벤트를
// 들으면 목록을 다시 불러온다 — 함수를 직접 부르는 결합이 없다.
//
// 사진은 multipart 가 아니라 본문으로 그대로 PUT 한다. 매물 id는 경로에 있고
// 파일은 하나이며 함께 보낼 필드가 없어서다 (app/routers/uploads.py 참고).

const UPLOAD_SOURCE = '직접등록';
const PAGE = 20;

// 서버가 받아들이는 형식. 여기서 걸러도 서버가 다시 검사한다 — 이 검사는
// 사용자에게 즉시 알려주기 위한 것이지 방어가 아니다. 방어는 서버에만 있다.
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const MAX_BYTES = 8 * 1024 * 1024;

const won = new Intl.NumberFormat('ko-KR');
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

const state = { offset: 0, q: '', items: [], total: 0, hasNext: false };

/* ------------------------------------------------------------- 렌더 */

function rowHtml(item) {
  const thumb = item.image_url
    ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">`
    : '<span>없음</span>';

  const price = item.price === null || item.price === undefined
    ? '가격 미상'
    : `${won.format(item.price)}원`;

  return `
    <tr>
      <td><span class="inv-thumb">${thumb}</span></td>
      <td>
        <div class="inv-title">${esc(item.title)}</div>
        <div class="inv-meta">${esc(item.brand ?? '')} · <span class="inv-price">${esc(price)}</span></div>
      </td>
      <td>${item.is_authenticated
        ? '<span class="badge-auth">정품인증</span>'
        : '<span class="badge-none">—</span>'}</td>
      <td>
        <input type="file" id="photo-${item.id}" accept="image/*" hidden
               data-photo-input="${item.id}">
        <label class="photo-pick" for="photo-${item.id}">${item.image_url ? '사진 교체' : '사진 올리기'}</label>
        <span class="photo-status" data-status="${item.id}"></span>
      </td>
    </tr>`;
}

function renderPager() {
  const page = Math.floor(state.offset / PAGE) + 1;
  const pages = Math.max(Math.ceil(state.total / PAGE), 1);

  $('invPager').innerHTML = state.total > PAGE
    ? `
      <button type="button" data-inv-page="prev"${state.offset === 0 ? ' disabled' : ''}>이전</button>
      <span class="pager-status">${page} / ${pages} · 총 ${won.format(state.total)}건</span>
      <button type="button" data-inv-page="next"${state.hasNext ? '' : ' disabled'}>다음</button>`
    : (state.total ? `<span class="pager-status">총 ${won.format(state.total)}건</span>` : '');
}

function setStatus(itemId, message, isError = false) {
  const cell = document.querySelector(`[data-status="${itemId}"]`);
  if (!cell) return;

  cell.textContent = message;
  cell.className = isError ? 'photo-status photo-status--error' : 'photo-status';
}

/* ------------------------------------------------------------- 로드 */

async function loadItems() {
  const body = $('invRows');

  body.innerHTML = '<tr><td colspan="4" class="inv-empty">불러오는 중…</td></tr>';

  try {
    const params = new URLSearchParams({
      source: UPLOAD_SOURCE,
      limit: String(PAGE),
      offset: String(state.offset),
      order_by: 'latest',
    });

    if (state.q) params.set('search', state.q);

    const res = await fetch(`/api/products?${params}`, { credentials: 'same-origin' });

    if (!res.ok) throw new Error(String(res.status));

    const data = await res.json();

    state.items = data.items;
    state.total = data.total;
    state.hasNext = data.has_next;

    body.innerHTML = data.items.length
      ? data.items.map(rowHtml).join('')
      : `<tr><td colspan="4" class="inv-empty">${state.q
        ? '검색 결과가 없습니다.'
        : '등록된 매물이 없습니다. <a href="#register">매물 등록</a> 또는 <a href="#bulk">CSV 일괄 등록</a>으로 시작하세요.'}</td></tr>`;

    renderPager();
    $('exportBtn').disabled = data.items.length === 0;
  } catch {
    body.innerHTML = '<tr><td colspan="4" class="inv-empty">매물을 불러오지 못했습니다.</td></tr>';
    $('exportBtn').disabled = true;
  }
}

/* ------------------------------------------------------ CSV 내보내기 */

function csvCell(value) {
  const s = String(value ?? '');

  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

/** 지금 화면에 보이는 페이지를 CSV로 내려받는다. 다시 올리면 그대로 갱신되는 형식이다. */
function exportCsv() {
  if (!state.items.length) return;

  const rows = [
    'title,price,url,brand,image_url,is_authenticated',
    ...state.items.map((it) => [
      it.title, it.price ?? '', it.item_url, it.brand ?? '',
      it.image_url ?? '', it.is_authenticated ? 'true' : '',
    ].map(csvCell).join(',')),
  ];

  const blob = new Blob(['\ufeff' + rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), {
    href: url,
    download: `reverdi-inventory-${new Date().toISOString().slice(0, 10)}.csv`,
  });

  a.click();
  URL.revokeObjectURL(url);
}

/* -------------------------------------------------------- 사진 업로드 */

async function upload(itemId, file) {
  if (!ACCEPTED.includes(file.type)) {
    setStatus(itemId, 'JPG·PNG·WEBP·GIF만 올릴 수 있습니다.', true);
    return;
  }

  if (file.size > MAX_BYTES) {
    setStatus(itemId, `파일이 너무 큽니다 (최대 ${MAX_BYTES / 1024 / 1024}MB).`, true);
    return;
  }

  setStatus(itemId, '올리는 중…');

  try {
    const res = await fetch(`/api/uploads/items/${itemId}/image`, {
      method: 'PUT',
      credentials: 'same-origin',
      // 서버는 이 헤더를 믿지 않는다. 실제 형식은 Pillow가 내용으로 판정한다.
      headers: { 'Content-Type': file.type },
      body: file,
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      setStatus(itemId, data.detail ?? `실패 (${res.status})`, true);
      return;
    }

    // 저장된 크기를 함께 보여준다. 서버가 재인코딩하며 긴 변을 1600px로 줄이므로
    // 올린 파일과 저장된 파일이 다르다.
    setStatus(itemId, `완료 · ${data.width}×${data.height}, ${Math.round(data.bytes / 1024)}KB`);

    const row = document.querySelector(`[data-status="${itemId}"]`)?.closest('tr');
    const thumb = row?.querySelector('.inv-thumb');

    if (thumb) {
      // 캐시 무력화. 같은 주소로 덮어쓰는 방식으로 바뀌어도 옛 사진이 남지 않게.
      thumb.innerHTML = `<img src="${esc(data.image_url)}?t=${Date.now()}" alt="">`;
    }
  } catch {
    setStatus(itemId, '네트워크 오류로 올리지 못했습니다.', true);
  }
}

/* ------------------------------------------------------------- 이벤트 */

document.addEventListener('change', (e) => {
  const input = e.target.closest('[data-photo-input]');
  if (!input || !input.files?.length) return;

  upload(input.dataset.photoInput, input.files[0]);
  // 같은 파일을 다시 고를 수 있게 비운다. 값이 남아 있으면 change가 안 뜬다.
  input.value = '';
});

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-inv-page]');
  if (!btn || btn.disabled) return;

  state.offset = btn.dataset.invPage === 'next'
    ? state.offset + PAGE
    : Math.max(state.offset - PAGE, 0);

  loadItems();
});

// 입력을 잠깐 기다렸다 검색한다. 타자마다 요청하면 글자 수만큼 서버를 두드린다.
let searchTimer = null;

$('invSearch').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = e.target.value.trim();
    state.offset = 0;
    loadItems();
  }, 300);
});

$('photoReload').addEventListener('click', loadItems);
$('exportBtn').addEventListener('click', exportCsv);

// 등록·업로드가 매물을 바꾸면 목록을 다시 불러온다.
window.addEventListener('reverdi:items-changed', () => {
  state.offset = 0;
  loadItems();
});

loadItems();
