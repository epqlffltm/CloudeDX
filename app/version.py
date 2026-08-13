# app/version.py

"""
프로젝트 버전을 한 곳에서 읽는다.

예전에는 pyproject.toml이 0.1.0, FastAPI 앱이 0.6.0으로 갈라져 있었다. 사소해
보이지만 릴리스 관리에서는 어느 쪽이 진짜인지 알 수 없게 되는 문제다.

`importlib.metadata.version()`을 쓰지 않는 이유:
    이 프로젝트는 패키지로 설치하지 않고 소스를 그대로 실행한다. dockerfile.backend가
    `uv sync --no-install-project`로 의존성만 설치하므로, 컨테이너 안에는 cloudedx라는
    distribution metadata가 아예 없다. 그 상태에서 version("cloudedx")를 부르면
    PackageNotFoundError가 난다.

    pyproject.toml은 두 이미지 모두에 복사되므로 그걸 직접 읽는 편이 확실하다.

읽기에 실패해도 앱이 뜨지 못하게 하지는 않는다. 버전 표시 하나 때문에 서비스가
안 뜨는 건 과하다.
"""

import tomllib
from pathlib import Path

FALLBACK_VERSION = "0.0.0"

# app/version.py 기준으로 두 단계 위가 프로젝트 루트다.
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def read_version() -> str:
    """pyproject.toml의 [project] version을 읽는다. 실패하면 대체값."""
    try:
        with _PYPROJECT.open("rb") as file:
            return tomllib.load(file)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        # 로깅 설정보다 먼저 임포트될 수 있어 print를 쓴다.
        print(f"[version] pyproject.toml에서 버전을 읽지 못해 {FALLBACK_VERSION} 을 씁니다.")
        return FALLBACK_VERSION


__version__ = read_version()