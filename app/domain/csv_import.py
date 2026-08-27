# app/domain/csv_import.py

"""
기업고객이 올린 CSV를 매물(CrawledItem)로 바꾸는 계층.

크롤러가 사이트에서 긁어오는 것과 목적지가 같다 — 둘 다 items 테이블로 간다.
그래서 여기서도 CrawledItem을 만들어 repository.upsert_items에 넘긴다. 저장 경로를
하나로 두면 제목 정제(clean_title), 브랜드 판정, 카테고리 분류, url 기준 중복 제거가
업로드분에도 똑같이 적용된다. 별도 경로를 만들면 "크롤링한 샤넬"과 "업로드한 샤넬"의
브랜드 표기가 갈라진다.

HTTP를 모르는 순수 함수로 둔다. 라우터는 바이트를 넘기고 결과를 받아 응답으로
바꾸기만 한다 — 테스트에서 파일 업로드를 흉내 낼 필요가 없다.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from app.domain.models import CrawledItem
from app.domain.sources import UPLOAD

# 업로드 출처 표기. 정본은 app/domain/sources.py에 있다 — 정품 인증 뱃지 판정이
# 같은 값을 보기 때문에 수집처 상수와 같은 곳에 둔다. 기존 임포트 경로를 쓰는
# 호출처가 있어 이름은 남겨 둔다.
UPLOAD_SOURCE = UPLOAD

# 필수 컬럼. 이 셋이 없으면 매물로 성립하지 않는다.
#   title  화면 카드 제목이자 브랜드·카테고리 판정의 입력
#   price  가격
#   url    중복 판정 키(items.url은 unique)
REQUIRED_COLUMNS = ("title", "price", "url")

OPTIONAL_COLUMNS = ("brand", "image_url", "region", "is_authenticated")

# 인증 컬럼에서 참으로 읽는 표기. 사람이 만든 시트라 표기가 제각각이고,
# 엑셀은 TRUE를 대문자로 저장한다. 목록에 없는 값은 전부 거짓으로 본다 —
# 애매한 값을 참으로 해석하면 없는 보증이 화면에 붙는다.
_TRUTHY = frozenset({"true", "1", "y", "yes", "o", "t", "인증", "정품인증", "예", "참"})

# 헤더 표기 흔들림을 흡수한다. 사람이 만든 CSV라 한글 헤더가 흔하고,
# 엑셀에서 저장하면 대문자나 공백이 섞인다.
_HEADER_ALIASES = {
    "title": "title", "제목": "title", "상품명": "title", "name": "title",
    "price": "price", "가격": "price", "판매가": "price",
    "url": "url", "링크": "url", "주소": "url", "link": "url",
    "brand": "brand", "브랜드": "brand",
    "image_url": "image_url", "이미지": "image_url", "image": "image_url", "썸네일": "image_url",
    "region": "region", "지역": "region",
    "is_authenticated": "is_authenticated", "인증": "is_authenticated",
    "정품인증": "is_authenticated", "정품": "is_authenticated",
    "authenticated": "is_authenticated", "verified": "is_authenticated",
}

# 최대 처리 행 수. 시연 규모를 넘어가는 파일은 거절한다 —
# 한 요청이 수십 초를 잡고 있으면 화면이 죽은 것처럼 보인다.
MAX_ROWS = 5_000

_DIGITS = re.compile(r"[0-9]+")


@dataclass
class ImportReport:
    """업로드 한 건의 결과. 화면이 그대로 표로 그린다."""

    total_rows: int = 0
    accepted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    items: list[CrawledItem] = field(default_factory=list)

    def add_error(self, line: int, message: str) -> None:
        self.skipped += 1

        # 오류를 전부 모으면 잘못 만든 파일 하나가 응답을 수 MB로 부풀린다.
        # 앞의 50건이면 무엇이 잘못됐는지 파악하기에 충분하다.
        if len(self.errors) < 50:
            self.errors.append(f"{line}행: {message}")


def parse_price(raw: str) -> int | None:
    """
    '4,300,000원', '430만', '430만원', '4300000' 을 원 단위 정수로.

    만 단위 표기를 따로 보는 이유: 사람이 만든 시트에는 '430만원'이 흔한데,
    숫자만 뽑으면 430원이 된다. 가격 필터와 시세 통계가 통째로 망가진다.
    """
    text = (raw or "").strip()

    if not text:
        return None

    digits = "".join(_DIGITS.findall(text))

    if not digits:
        return None

    value = int(digits)

    # '만'이 붙어 있고 그 뒤에 '원'말고 다른 숫자가 없으면 만 단위로 본다.
    if "만" in text and not re.search(r"만\s*[0-9]", text):
        value *= 10_000

    return value or None


def _normalize_header(name: str) -> str | None:
    key = (name or "").strip().lower().lstrip("\ufeff")
    return _HEADER_ALIASES.get(key)


def parse_csv(raw: bytes) -> ImportReport:
    """
    CSV 바이트를 읽어 매물 목록과 처리 결과를 만든다. 예외를 던지지 않는다 —
    행 하나가 잘못됐다고 파일 전체를 버리면 사용자가 고칠 곳을 알 수 없다.
    """
    report = ImportReport()

    # 엑셀에서 저장한 한글 CSV는 cp949인 경우가 많다. UTF-8부터 시도하고
    # 실패하면 cp949로 되짚는다. BOM은 utf-8-sig가 걷어낸다.
    text: str | None = None

    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        report.errors.append("파일 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949로 저장해 주세요.")
        return report

    reader = csv.reader(io.StringIO(text))

    try:
        header = next(reader)
    except StopIteration:
        report.errors.append("빈 파일입니다.")
        return report

    # 열 위치 → 표준 컬럼명
    columns = {i: col for i, name in enumerate(header) if (col := _normalize_header(name))}
    present = set(columns.values())
    missing = [c for c in REQUIRED_COLUMNS if c not in present]

    if missing:
        report.errors.append(
            f"필수 컬럼이 없습니다: {', '.join(missing)} "
            f"(첫 줄에 {', '.join(REQUIRED_COLUMNS)} 이 있어야 합니다)"
        )
        return report

    seen_urls: set[str] = set()

    for line, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue  # 빈 줄. 엑셀 저장본 끝에 흔하다

        report.total_rows += 1

        if report.total_rows > MAX_ROWS:
            report.errors.append(f"{MAX_ROWS}행을 넘어 나머지를 건너뛰었습니다.")
            break

        value = {col: (row[i].strip() if i < len(row) else "") for i, col in columns.items()}

        title = value.get("title", "")
        url = value.get("url", "")

        if not title:
            report.add_error(line, "제목이 비어 있습니다.")
            continue

        if not url:
            report.add_error(line, "링크가 비어 있습니다.")
            continue

        if not url.startswith(("http://", "https://")):
            report.add_error(line, "링크는 http:// 또는 https:// 로 시작해야 합니다.")
            continue

        if len(url) > 500:
            report.add_error(line, "링크가 너무 깁니다 (500자 제한).")
            continue

        if url in seen_urls:
            report.add_error(line, "같은 파일 안에서 링크가 중복됩니다.")
            continue

        price_raw = value.get("price", "")
        price_value = parse_price(price_raw)

        if price_value is None:
            report.add_error(line, f"가격을 읽을 수 없습니다: {price_raw!r}")
            continue

        seen_urls.add(url)

        report.items.append(
            CrawledItem(
                source=UPLOAD_SOURCE,
                # 브랜드는 비워 두면 제목에서 판정한다(repository의 clean_title).
                # 시트에 적힌 값은 검색어 자리로만 넘긴다.
                brand=value.get("brand", "") or "",
                title=title,
                price=price_raw,
                price_value=price_value,
                region=value.get("region") or None,
                time_text=None,
                image_url=value.get("image_url") or None,
                url=url,
                is_sold=False,
                seller_type=None,
                # 정품 인증 표시. 이 값만으로는 뱃지가 켜지지 않는다 —
                # repository가 source까지 함께 보고 결정한다. 여기서 하는 일은
                # 시트에 적힌 표기를 불리언으로 읽는 것뿐이다.
                is_authenticated=value.get("is_authenticated", "").strip().lower() in _TRUTHY,
            )
        )
        report.accepted += 1

    return report
