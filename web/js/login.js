// web/js/login.js
//
// 로그인 화면. 성공하면 역할에 맞는 페이지로 보낸다.

import { fetchMe, login } from './auth.js';

const $ = (id) => document.getElementById(id);

const homeFor = (role) => (role === 'admin' ? 'admin.html' : 'client.html');

function showError(message) {
  const box = $('loginError');
  box.textContent = message;
  box.hidden = false;
}

async function init() {
  // 이미 로그인돼 있으면 폼을 보여줄 이유가 없다.
  const me = await fetchMe();

  if (me) {
    location.replace(homeFor(me.role));
    return;
  }

  // 비밀번호 표시 토글. input의 type을 password <-> text로 바꾸는 것이 전부다.
  // aria-pressed는 CSS가 눈/빗금눈 아이콘을 고르는 기준이자, 스크린리더에
  // "지금 보이는 상태인가"를 알리는 값이다.
  const toggle = $('pwToggle');

  if (toggle) {
    toggle.addEventListener('click', () => {
      const pw = $('password');
      const show = pw.type === 'password';

      pw.type = show ? 'text' : 'password';
      toggle.setAttribute('aria-pressed', String(show));
      pw.focus();
    });
  }

  // 시연 계정 칸을 누르면 입력칸이 채워진다. 발표 중에 오타로 막히지 않게.
  for (const row of document.querySelectorAll('[data-fill]')) {
    row.addEventListener('click', () => {
      const who = row.dataset.fill;
      $('username').value = who;
      $('password').value = `${who}1234`;
      $('loginError').hidden = true;
      $('password').focus();
    });
  }

  $('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const submit = $('loginSubmit');
    const username = $('username').value.trim();
    const password = $('password').value;

    if (!username || !password) {
      showError('아이디와 비밀번호를 모두 입력해 주세요.');
      return;
    }

    // 연타로 요청이 겹치는 것을 막는다.
    submit.disabled = true;
    submit.textContent = '확인 중…';
    $('loginError').hidden = true;

    try {
      const user = await login(username, password);
      location.replace(homeFor(user.role));
    } catch (err) {
      showError(err.message);
      submit.disabled = false;
      submit.textContent = '로그인';
      $('password').select();
    }
  });
}

init();
