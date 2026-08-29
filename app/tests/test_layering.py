# app/tests/test_layering.py

"""
계층 경계가 지켜지는지 검사한다.

백엔드 이미지에는 Playwright가 없다(dockerfile.backend). 그래서 백엔드가 임포트하는
어떤 모듈도 app.crawler 를 최상단에서 끌어오면 안 된다. 규칙을 README에 적어두는
것만으로는 부족해서 — 사람은 잊는다 — 소스를 직접 훑어 검사한다.

CI의 test 잡이 Playwright 없이 도는 것도 같은 규칙을 지키는 장치지만, 그쪽은 "앱이
뜨는가"만 본다. 여기는 어느 파일의 몇 번째 줄이 규칙을 어겼는지 짚어준다.

app/crawler/runner.py 가 예외로 허용되는 이유: 실행 규칙만 담고 Playwright를 임포트하지
않는다. main.py 가 크롤러를 띄울 때 이 모듈을 쓰지만, 그것도 lifespan 안에서 지연
임포트라 백엔드 이미지에서는 실행되지 않는다.
"""

import ast
import pathlib

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]

# 백엔드 프로세스가 임포트하는 영역. 이 안에서는 app.crawler 를 최상단 임포트할 수 없다.
BACKEND_PACKAGES = ("db", "domain", "routers", "schemas")

# Playwright를 끌고 오지 않는 크롤러 모듈. 여기는 백엔드가 참조해도 안전하다.
CRAWLER_SAFE_MODULES = {
    "app.crawler.runner",
    "app.crawler.bunjang.config",
    "app.crawler.bunjang.crawler",
}


def iter_python_files(package: str):
    for path in (APP_ROOT / package).rglob("*.py"):
        if "__pycache__" not in str(path):
            yield path


def top_level_imports(path: pathlib.Path) -> list[tuple[str, int]]:
    """
    모듈 최상단에서 실행되는 임포트만 뽑는다.

    함수 안의 임포트는 제외한다. app/main.py 처럼 조건부로만 크롤러를 부르는 경우가
    있고, 그건 백엔드 이미지에서 실행되지 않으므로 규칙 위반이 아니다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))

    return found


@pytest.mark.parametrize("package", BACKEND_PACKAGES)
def test_backend_does_not_import_crawler(package):
    violations = []

    for path in iter_python_files(package):
        for module, lineno in top_level_imports(path):
            if module.startswith("app.crawler") and module not in CRAWLER_SAFE_MODULES:
                violations.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno} -> {module}")

    assert not violations, (
        "백엔드 코드가 크롤러를 최상단에서 임포트합니다. 백엔드 이미지에는 Playwright가 "
        "없어서 이대로면 앱이 뜨지 않습니다. 공유해야 할 값이면 app/domain/ 으로 옮기세요.\n"
        + "\n".join(violations)
    )


def test_domain_stays_dependency_free():
    """
    app/domain/ 은 양쪽이 쓰는 순수 어휘다. 여기에 무거운 의존성이 들어오면 백엔드
    이미지가 그걸 지고 다녀야 하고, 애초에 이 패키지를 나눈 의미가 사라진다.
    """
    forbidden = ("playwright", "app.crawler", "app.db", "app.routers", "fastapi", "sqlalchemy")
    violations = []

    for path in iter_python_files("domain"):
        for module, lineno in top_level_imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno} -> {module}")

    assert not violations, "app/domain/ 은 순수 파이썬만 담아야 합니다.\n" + "\n".join(violations)


def test_runner_has_no_playwright():
    """
    runner.py 가 Playwright를 끌어오는 순간 크롤러 실행 규칙을 브라우저 없이 테스트할
    수 없게 된다. 사이트별 구현은 scheduler.py 로 가야 한다.
    """
    runner = APP_ROOT / "crawler" / "runner.py"
    modules = [module for module, _ in top_level_imports(runner)]

    assert not any(m.startswith("playwright") for m in modules)
    assert not any(m.startswith("app.crawler.daangn") for m in modules)
    assert not any(m.startswith("app.crawler.joongna") for m in modules)