# app/domain/storage.py

"""
업로드 이미지의 저장 위치와 파일명 규칙.

**web/ 아래에 두지 않는다.** web/은 도커 이미지에 구워지고 git에 들어가는
디렉토리라, 그 밑에 업로드를 받으면 사용자가 올린 파일이 커밋될 수 있고 이미지를
새로 빌드할 때마다 사라진다. 별도 볼륨(/srv/uploads)에 두고 앱이 마운트해서 서빙한다.

크롤링 이미지와 성격이 다르다는 점이 중요하다. 크롤링분은 수집처 CDN의 URL을 그대로
참조하는데, 그건 남의 파일이라 지울 수도 없고 지울 이유도 없다. 업로드분은 우리가
소유한 파일이고, 판매자가 매물을 내리면 같이 지우면 그만이라 고아 파일 문제가 없다.

**파일명은 우리가 짓는다.** 원본 이름을 쓰면 두 가지가 들어온다 — 경로 조작
("../../etc/passwd")과 확장자 위조("사진.jpg.php"). 이름을 새로 만들면 둘 다
성립하지 않는다. 원본 이름이 필요하면 DB 컬럼에 따로 담을 일이지 파일명으로 쓸
값이 아니다.
"""

import secrets
from datetime import UTC, datetime
from pathlib import Path

from app.config import UPLOAD_DIR


def build_object_name(extension: str) -> str:
    """
    저장할 상대 경로를 만든다. 예: 2026/08/3f9a1c2b8e4d5a67.jpg

    연·월로 디렉토리를 나누는 이유는 한 디렉토리에 파일이 수만 개 쌓이면 목록
    조회가 느려지고 백업·정리가 번거로워지기 때문이다.

    이름은 난수다. 순번을 쓰면 남의 이미지 주소를 세어 볼 수 있다 — 판매자가 아직
    공개하지 않은 매물의 사진이 주소만으로 노출된다.
    """
    now = datetime.now(UTC)

    return f"{now:%Y/%m}/{secrets.token_hex(16)}{extension}"


def resolve_upload_path(object_name: str) -> Path:
    """
    상대 경로를 실제 저장 경로로 바꾼다. 업로드 루트를 벗어나면 ValueError.

    경로 조작 방어다. build_object_name이 만든 이름만 쓰는 한 벗어날 수 없지만,
    나중에 DB에 담긴 값을 그대로 넘기는 호출부가 생길 수 있다. 그때 이 검사가
    유일한 방어선이 된다.
    """
    root = UPLOAD_DIR.resolve()
    target = (root / object_name).resolve()

    if not target.is_relative_to(root):
        raise ValueError("업로드 경로를 벗어났습니다.")

    return target


def save_image(data: bytes, extension: str) -> str:
    """이미지를 저장하고, 화면이 쓸 상대 경로를 돌려준다."""
    object_name = build_object_name(extension)
    path = resolve_upload_path(object_name)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    return object_name


def public_url(object_name: str | None) -> str | None:
    """저장 경로를 화면이 쓸 URL로 바꾼다."""
    if not object_name:
        return None

    return f"/uploads/{object_name}"


def delete_image(object_name: str) -> None:
    """
    이미지를 지운다. 이미 없으면 조용히 넘어간다.

    파일이 없다는 것은 대개 이전 삭제가 성공했다는 뜻이라, 그것을 오류로 올리면
    재시도가 영영 실패한다.
    """
    try:
        resolve_upload_path(object_name).unlink(missing_ok=True)
    except ValueError:
        # 경로가 루트를 벗어난 값이면 우리가 만든 파일이 아니다. 지우지 않는다.
        return
