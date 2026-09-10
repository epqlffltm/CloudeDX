// web/js/home_auth.js
//
// 메인 헤더의 계정 링크를 실제 서버 세션과 동기화한다.
// 비로그인: 로그인
// 기업고객: My Inventory
// 관리자: Console

import { fetchMe } from './auth.js';

let syncing = false;

async function syncAccountLink() {
  const link = document.getElementById('loginBtn');
  if (!link || syncing) return;

  syncing = true;

  try {
    const me = await fetchMe();

    if (!me) {
      link.textContent = '로그인';
      link.href = 'login.html';
      link.setAttribute('aria-label', '로그인 화면으로 이동');
      return;
    }

    if (me.role === 'admin') {
      link.textContent = 'Console';
      link.href = 'admin.html';
      link.setAttribute('aria-label', '관리자 콘솔로 이동');
      return;
    }

    link.textContent = 'My Inventory';
    link.href = 'client.html';
    link.setAttribute('aria-label', '내 매물 관리로 이동');
  } finally {
    syncing = false;
  }
}

syncAccountLink();

// 브라우저 뒤로가기로 메인이 bfcache에서 복원되면 상태를 다시 읽는다.
window.addEventListener('pageshow', () => {
  syncAccountLink();
});

// 다른 탭에서 로그인/로그아웃한 뒤 돌아오는 경우도 다시 읽는다.
window.addEventListener('focus', () => {
  syncAccountLink();
});
