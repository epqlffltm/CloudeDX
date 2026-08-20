// web/js/auth.js
//
// 로그인 관련 호출. 세션은 HttpOnly 쿠키라 JS가 토큰을 들고 다니지 않는다 —
// 같은 출처라 fetch에 자동으로 실린다. 여기서는 credentials만 챙기면 된다.

const OPTS = { credentials: 'same-origin' };

/**
 * 지금 로그인한 사람. 비로그인이면 null.
 * 서버가 비로그인을 401이 아니라 200 + null로 주므로 여기서도 예외가 아니다.
 */
export async function fetchMe() {
  const res = await fetch('/api/auth/me', OPTS);

  if (!res.ok) return null;

  return res.json();
}

export async function login(username, password) {
  const res = await fetch('/api/auth/login', {
    ...OPTS,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `로그인에 실패했습니다. (${res.status})`);
  }

  return res.json();
}

export async function logout() {
  await fetch('/api/auth/logout', { ...OPTS, method: 'POST' });
}

/**
 * 이 페이지에 들어올 자격이 있는지 확인하고, 아니면 돌려보낸다.
 *
 * 화면 단속은 편의일 뿐 보안이 아니다 — 진짜 방어는 서버의 require_role이다.
 * 여기서 막는 이유는 권한 없는 사람이 빈 화면과 401 오류를 보는 대신
 * 갈 곳으로 바로 가게 하려는 것이다.
 *
 * @returns 통과한 사용자. 통과하지 못하면 이동 후 null.
 */
export async function guard(requiredRole) {
  const me = await fetchMe();

  if (!me) {
    location.replace('login.html');
    return null;
  }

  if (me.role !== requiredRole) {
    // 로그인은 했는데 역할이 다르다. 로그인 화면으로 보내면 다시 로그인해도
    // 같은 곳에 막히므로, 자기 자리로 보낸다.
    location.replace(me.role === 'admin' ? 'admin.html' : 'client.html');
    return null;
  }

  return me;
}

/** 상단 사용자 표시줄. 계정 페이지 두 곳이 같은 모양을 쓴다. */
export function renderAccountBar(me) {
  const box = document.getElementById('accountBar');
  if (!box || !me) return;

  box.innerHTML = `
    <span class="account-chip">
      <strong>${me.username}</strong>
      <span class="account-chip__role">${me.display_role}</span>
    </span>
    <button type="button" class="btn-reset" id="logoutBtn">로그아웃</button>`;

  document.getElementById('logoutBtn').addEventListener('click', async () => {
    await logout();
    location.replace('./');
  });
}
