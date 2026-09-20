// web/js/login.js
//
// 로그인 화면. 성공하면 역할에 맞는 페이지로 보낸다.
// 이미 유효한 서버 세션이 있으면 로그인 폼을 다시 보여주지 않는다.

import { fetchMe, login } from './auth.js';

const $ = (id) => document.getElementById(id);

const homeFor = (role) => (role === 'admin' ? 'admin.html' : 'client.html');

function showError(message) {
  const box = $('loginError');
  box.textContent = message;
  box.hidden = false;
}

async function init() {
  // 유효한 서버 세션이 이미 있으면 자기 관리 화면으로 바로 이동한다.
  const me = await fetchMe();
  if (me) {
    location.replace(homeFor(me.role));
    return;
  }

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

  $('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const submit = $('loginSubmit');
    const username = $('username').value.trim();
    const password = $('password').value;

    if (!username || !password) {
      showError('아이디와 비밀번호를 모두 입력해 주세요.');
      return;
    }

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
