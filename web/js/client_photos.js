// web/js/client_photos.js

/*
 * 등록한 매물에 사진 붙이기.
 *
 * CSV로 매물을 먼저 올린 뒤, 목록에서 골라 사진을 하나씩 붙이는 흐름이다.
 * 이미지 주소를 갖고 있는 판매자는 CSV의 image_url 컬럼을 쓰면 되고, 사이트가
 * 없어 올릴 곳이 없는 판매자를 위한 경로가 이쪽이다.
 *
 * 파일을 multipart가 아니라 본문으로 그대로 PUT한다. 매물 id는 경로에 있고
 * 파일은 하나이며 함께 보낼 필드가 없어서, CSV 업로드와 같은 이유로 multipart가
 * 주는 이점이 없다.
 *
 * client.js와 별도 파일인 이유는 두 기능이 서로를 몰라도 되기 때문이다. CSV
 * 업로드는 사진 없이 완결되고, 사진 붙이기는 CSV를 올린 뒤 언제든 따로 한다.
 */

const UPLOAD_SOURCE = '직접등록';

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

function setStatus(itemId, message, isError = false) {
  const cell = document.querySelector(`[data-status="${itemId}"]`);
  if (!cell) return;

  cell.textContent = message;
  cell.className = isError ? 'photo-status photo-status--error' : 'photo-status';
}

function rowHtml(item) {
  const thumb = item.image_url
    ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">`
    : '<span>없음</span>';

  return `
    <tr>
      <td class="photo-thumb${item.image_url ? '' : ' photo-thumb--empty'}">${thumb}</td>
      <td>
        <div class="photo-title">${esc(item.title)}</div>
        <div class="photo-meta">${esc(item.brand ?? '')} · ${
          item.price === null || item.price === undefined
            ? '가격 미상'
            : `${won.format(item.price)}원`
        }</div>
      </td>
      <td>
        <input type="file" id="photo-${item.id}" accept="image/*" hidden
               data-photo-input="${item.id}">
        <label class="btn-reset photo-pick" for="photo-${item.id}">사진 선택</label>
        <span class="photo-status" data-status="${item.id}"></span>
      </td>
    </tr>`;
}

async function loadItems() {
  const body = $('photoRows');

  body.innerHTML = '<tr><td colspan="3" class="photo-empty">불러오는 중…</td></tr>';

  try {
    const params = new URLSearchParams({
      source: UPLOAD_SOURCE,
      limit: '50',
      order_by: 'latest',
    });
    const res = await fetch(`/api/products?${params}`, { credentials: 'same-origin' });

    if (!res.ok) throw new Error(String(res.status));

    const data = await res.json();

    body.innerHTML = data.items.length
      ? data.items.map(rowHtml).join('')
      : '<tr><td colspan="3" class="photo-empty">등록된 매물이 없습니다. CSV를 먼저 올려 주세요.</td></tr>';
  } catch {
    body.innerHTML = '<tr><td colspan="3" class="photo-empty">매물을 불러오지 못했습니다.</td></tr>';
  }
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
      // 서버는 이 헤더를 믿지 않는다. 실제 형식은 Pillow가 내용으로 판정한다.
      headers: { 'Content-Type': file.type },
      body: file,
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      setStatus(itemId, data.detail ?? `실패 (${res.status})`, true);
      return;
    }

    // 저장된 크기를 함께 보여준다. 서버가 원본을 그대로 두지 않고 재인코딩하며
    // 긴 변을 1600px로 줄이므로, 올린 파일과 저장된 파일이 다르다.
    setStatus(itemId, `완료 · ${data.width}×${data.height}, ${Math.round(data.bytes / 1024)}KB`);

    const thumb = document.querySelector(`[data-status="${itemId}"]`)
      ?.closest('tr')?.querySelector('.photo-thumb');

    if (thumb) {
      thumb.classList.remove('photo-thumb--empty');
      // 캐시 무력화. 주소가 매번 새로 만들어지므로 사실 필요 없지만, 같은
      // 주소로 덮어쓰는 방식으로 바뀌어도 화면이 옛 사진을 보여주지 않게 한다.
      thumb.innerHTML = `<img src="${esc(data.image_url)}?t=${Date.now()}" alt="">`;
    }
  } catch {
    setStatus(itemId, '네트워크 오류로 올리지 못했습니다.', true);
  }
}

document.addEventListener('change', (e) => {
  const input = e.target.closest('[data-photo-input]');
  if (!input || !input.files?.length) return;

  upload(input.dataset.photoInput, input.files[0]);
  // 같은 파일을 다시 고를 수 있게 비운다. 값이 남아 있으면 change가 안 뜬다.
  input.value = '';
});

$('photoReload')?.addEventListener('click', loadItems);

loadItems();
