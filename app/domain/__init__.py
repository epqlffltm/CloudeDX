# app/domain/__init__.py

"""
백엔드와 크롤러가 함께 쓰는 도메인 어휘.

이 패키지를 따로 둔 이유는 두 실행 단위가 서로 다른 이미지로 배포되기 때문이다.
백엔드 이미지에는 Playwright가 없으므로(dockerfile.backend 참고), 백엔드가 임포트하는
모듈은 무엇도 Playwright를 끌고 오면 안 된다.

예전에는 이 모듈들이 app/crawler/ 안에 있었다. Playwright를 안 쓰니 동작은 했지만
이름이 사실과 달랐고 — 크롤러 전용처럼 보이는데 실제로는 라우터와 repository도
가져다 썼다 — 누군가 여기에 Playwright 임포트를 하나 추가하면 백엔드 이미지가 죽는
구조였다. 그걸 막는 장치가 CI 검사 하나뿐이었다.

경계는 이렇게 읽으면 된다.

    app/domain/     양쪽이 쓴다. 순수 파이썬만. 무거운 의존성 금지.
    app/crawler/    Playwright가 필요한 것만. 백엔드에서 임포트하지 않는다.
    app/db/         저장. domain은 임포트해도 되지만 crawler는 안 된다.
    app/routers/    서빙. 마찬가지.
"""