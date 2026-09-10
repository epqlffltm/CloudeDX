// web/js/auth.js
//
// 로그인 관련 호출.
// 세션의 정본은 서버가 발급한 HttpOnly 쿠키다.
// sessionStorage는 표시 편의를 위한 보조 정보일 뿐, 로그인 판정에는 사용하지 않는다.

const OPTS = {
  credentials: 'same-origin',
  cache: 'no-store',
};

function rememberRole(role) {
  try {
    if (role) {
      sessionStorage.setItem('reverdi_role', role);
    } else {
      sessionStorage.removeItem('reverdi_role');
    }
  } catch {
    // sessionStorage를 쓸 수 없어도 서버 세션에는 영향이 없다.
  }
}

/**
 * 지금 로그인한 사람. 비로그인이면 null.
 *
 * 반드시 서버 /api/auth/me를 확인한다.
 * URL 파라미터나 sessionStorage 값만으로 로그인 사용자 객체를 만들지 않는다.
 */
export async function fetchMe() {
  try {
    const res = await fetch('/api/auth/me', OPTS);

    if (!res.ok) {
      rememberRole(null);
      return null;
    }

    const data = await res.json();

    if (!data?.role) {
      rememberRole(null);
      return null;
    }

    rememberRole(data.role);
    return data;
  } catch {
    // 네트워크 오류를 로그인 성공으로 추정하지 않는다.
    return null;
  }
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

  const user = await res.json();
  rememberRole(user?.role ?? null);
  return user;
}

export async function logout() {
  rememberRole(null);
  await fetch('/api/auth/logout', {
    ...OPTS,
    method: 'POST',
  });
}

/**
 * 이 페이지에 들어올 자격이 있는지 확인하고, 아니면 적절한 페이지로 보낸다.
 * 실제 권한 검사는 서버의 require_role이 담당한다.
 */
export async function guard(requiredRole) {
  const me = await fetchMe();

  if (!me) {
    location.replace('login.html');
    return null;
  }

  if (me.role !== requiredRole) {
    location.replace(me.role === 'admin' ? 'admin.html' : 'client.html');
    return null;
  }

  return me;
}

/** 상단 사용자 표시줄. 관리자/기업고객 화면이 같은 모양을 쓴다. */
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
