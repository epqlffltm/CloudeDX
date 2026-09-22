// web/js/client_photos.js
// 현재 로그인한 판매자의 직접등록 매물만 조회하고, 사진을 등록하거나 매물을 내린다.
//
// '내리기'는 서버에서 is_active=False 로 바꾸는 것이다. 행이 지워지지 않으므로
// 같은 매물을 CSV 로 다시 올리면 되살아난다 (app/routers/uploads.py 참고).

const PAGE = 20;
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
        <button type="button" class="inv-delete" data-delete="${item.id}"
                data-title="${esc(item.title)}">내리기</button>
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

async function loadItems() {
  const body = $('invRows');
  body.innerHTML = '<tr><td colspan="4" class="inv-empty">불러오는 중…</td></tr>';

  try {
    const params = new URLSearchParams({
      limit: String(PAGE),
      offset: String(state.offset),
    });
    if (state.q) params.set('search', state.q);

    const res = await fetch(`/api/uploads/items?${params}`, {
      credentials: 'same-origin',
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw new Error(data.detail ?? `매물을 불러오지 못했습니다. (${res.status})`);
    }

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
  } catch (err) {
    body.innerHTML = `<tr><td colspan="4" class="inv-empty">${esc(err.message || '매물을 불러오지 못했습니다.')}</td></tr>`;
    $('exportBtn').disabled = true;
  }
}

function csvCell(value) {
  const s = String(value ?? '');
  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

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
      headers: { 'Content-Type': file.type },
      body: file,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(itemId, data.detail ?? `실패 (${res.status})`, true);
      return;
    }

    setStatus(itemId, `완료 · ${data.width}×${data.height}, ${Math.round(data.bytes / 1024)}KB`);

    const row = document.querySelector(`[data-status="${itemId}"]`)?.closest('tr');
    const thumb = row?.querySelector('.inv-thumb');
    if (thumb) {
      thumb.innerHTML = `<img src="${esc(data.image_url)}?t=${Date.now()}" alt="">`;
    }
  } catch {
    setStatus(itemId, '네트워크 오류로 올리지 못했습니다.', true);
  }
}

/**
 * 매물 내리기. 서버가 is_active=False 로 바꾸면 목록에서 사라진다.
 *
 * 성공 후 목록을 다시 불러오는 이유: 이 페이지의 마지막 한 건을 내렸을 때
 * 행만 지우면 빈 표가 남고 페이지 수도 틀어진다. 서버에서 다시 받아 맞춘다.
 */
async function removeItem(itemId, title) {
  if (!window.confirm(`'${title}' 매물을 목록에서 내립니다.\n\n계속할까요?`)) return;

  const btn = document.querySelector(`[data-delete="${itemId}"]`);
  if (btn) btn.disabled = true;
  setStatus(itemId, '내리는 중…');

  try {
    const res = await fetch(`/api/uploads/items/${itemId}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(itemId, data.detail ?? `내리지 못했습니다. (${res.status})`, true);
      if (btn) btn.disabled = false;
      return;
    }

    // 표와 집계(관리자 화면의 매물 수)가 같이 갱신되도록 같은 이벤트를 쏜다.
    window.dispatchEvent(new CustomEvent('reverdi:items-changed'));
  } catch {
    setStatus(itemId, '네트워크 오류로 내리지 못했습니다.', true);
    if (btn) btn.disabled = false;
  }
}

document.addEventListener('change', (e) => {
  const input = e.target.closest('[data-photo-input]');
  if (!input || !input.files?.length) return;
  upload(input.dataset.photoInput, input.files[0]);
  input.value = '';
});

document.addEventListener('click', (e) => {
  const del = e.target.closest('[data-delete]');
  if (del && !del.disabled) {
    removeItem(del.dataset.delete, del.dataset.title);
    return;
  }

  const btn = e.target.closest('[data-inv-page]');
  if (!btn || btn.disabled) return;
  state.offset = btn.dataset.invPage === 'next'
    ? state.offset + PAGE
    : Math.max(state.offset - PAGE, 0);
  loadItems();
});

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

window.addEventListener('reverdi:items-changed', () => {
  state.offset = 0;
  loadItems();
});

loadItems();
