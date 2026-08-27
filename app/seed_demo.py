# app/seed_demo.py

"""
시연용 입점 판매자·매물 시드.

    docker compose run --rm backend python -m app.seed_demo

**모든 값이 가짜다.** 사업자등록번호는 형식만 맞는 연속 숫자(123-45-67890)이고,
전화번호도 예시 번호다. 형식까지 틀린 값을 쓰지 않는 이유는 나중에 실제 검증을
붙일 때 시드 데이터가 전부 걸리기 때문이다.

**좌표를 직접 넣는다.** 백엔드가 폐쇄망에 있어 브이월드 지오코더를 호출할 수 없다.
주소가 어차피 가짜라 지오코딩할 실체도 없고, 지도에 핀이 해당 지역 근처에 찍히면
시연에는 충분하다. 실제 운영에서 주소→좌표 변환이 필요해지면 브라우저가 지오코더를
호출해 폼에 채우는 방식으로 붙인다 — 그러면 백엔드는 끝까지 외부망을 타지 않는다.

이미지는 브랜드·모델 이름을 얹은 단색 플레이스홀더를 생성한다. 실제 제품 사진이
아니고, 그렇게 보이지도 않는다. 업로드 저장 경로와 서빙 경로를 실제로 태우는 것이
목적이라 시연에는 이것으로 충분하다.

멱등하다. 사업자등록번호와 매물 url이 유니크 키라 여러 번 돌려도 중복되지 않는다.
"""

import asyncio
import io
import logging
import random

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import ItemRecord, Seller
from app.domain.image_security import sanitize_image
from app.domain.sellers import check_seller, normalize_business_number
from app.domain.storage import public_url, save_image

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")

# 재현 가능한 시드. 돌릴 때마다 가격이 달라지면 화면 스크린샷을 비교할 수 없다.
RNG = random.Random(20260827)

SOURCE = "직접등록"

# 판매자 8명. 매장 있음 5, 없음 3.
#
# 좌표는 해당 지역의 대략적인 값이다. 주소가 가짜라 정확할 수 없고, 정확할 필요도
# 없다 — 지도에 핀이 그 동네에 찍히면 된다.
SELLERS = [
    {
        "name": "청담 명품관",
        "business_number": "123-45-67890",
        "phone": "02-1234-5678",
        "has_store": True,
        "address": "서울특별시 강남구 청담동 1-1 (시연용 가상 주소)",
        "latitude": 37.5251,
        "longitude": 127.0530,
        "description": "청담동 매장에서 직접 검수한 상품만 취급합니다.",
    },
    {
        "name": "명동 럭셔리",
        "business_number": "234-56-78901",
        "phone": "02-2345-6789",
        "has_store": True,
        "address": "서울특별시 중구 명동길 2-2 (시연용 가상 주소)",
        "latitude": 37.5636,
        "longitude": 126.9827,
        "description": "1998년부터 명동에서 영업 중인 중고 명품 전문점입니다.",
    },
    {
        "name": "해운대 빈티지",
        "business_number": "345-67-89012",
        "phone": "051-345-6789",
        "has_store": True,
        "address": "부산광역시 해운대구 우동 3-3 (시연용 가상 주소)",
        "latitude": 35.1631,
        "longitude": 129.1636,
        "description": "빈티지 라인 위주로 소량만 들여옵니다.",
    },
    {
        "name": "대구 로데오 상사",
        "business_number": "456-78-90123",
        "phone": "053-456-7890",
        "has_store": True,
        "address": "대구광역시 중구 동성로 4-4 (시연용 가상 주소)",
        "latitude": 35.8688,
        "longitude": 128.5952,
        "description": "지역 최대 규모 재고를 보유하고 있습니다.",
    },
    {
        "name": "판교 컬렉터스",
        "business_number": "567-89-01234",
        "phone": "031-567-8901",
        "has_store": True,
        "address": "경기도 성남시 분당구 판교역로 5-5 (시연용 가상 주소)",
        "latitude": 37.3948,
        "longitude": 127.1112,
        "description": "시계와 주얼리 중심으로 취급합니다.",
    },
    # 매장 없이 온라인으로만 파는 판매자. address와 좌표가 없는 것이 정상이고,
    # 화면은 이 경우 지도를 아예 그리지 않는다.
    {
        "name": "온라인 셀렉트",
        "business_number": "678-90-12345",
        "phone": "010-1234-5678",
        "has_store": False,
        "address": None,
        "latitude": None,
        "longitude": None,
        "description": "매장 없이 온라인으로만 판매합니다. 택배 거래만 가능합니다.",
    },
    {
        "name": "리셀 아카이브",
        "business_number": "789-01-23456",
        "phone": "010-2345-6789",
        "has_store": False,
        "address": None,
        "latitude": None,
        "longitude": None,
        "description": "개인 컬렉션을 정리해 판매합니다.",
    },
    {
        "name": "프리미엄 트레이드",
        "business_number": "890-12-34567",
        "phone": "010-3456-7890",
        "has_store": False,
        "address": None,
        "latitude": None,
        "longitude": None,
        "description": "해외 구매대행 및 위탁 판매를 병행합니다.",
    },
]

# (브랜드, 모델, 카테고리, 가격 하한, 가격 상한)
CATALOG = [
    ("샤넬", "클래식 플랩백 미디움", "bag", 8_000_000, 13_000_000),
    ("샤넬", "보이백 스몰", "bag", 5_500_000, 8_500_000),
    ("샤넬", "코코핸들 미니", "bag", 6_000_000, 9_000_000),
    ("루이비통", "네버풀 MM", "bag", 1_800_000, 2_900_000),
    ("루이비통", "온더고 MM", "bag", 2_800_000, 4_200_000),
    ("루이비통", "알마 BB", "bag", 1_500_000, 2_400_000),
    ("구찌", "마몬트 스몰 숄더백", "bag", 1_300_000, 2_100_000),
    ("구찌", "디오니소스 미니", "bag", 1_600_000, 2_600_000),
    ("에르메스", "가든파티 36", "bag", 4_500_000, 7_000_000),
    ("에르메스", "에블린 PM", "bag", 3_800_000, 6_000_000),
    ("프라다", "리나일론 숄더백", "bag", 900_000, 1_600_000),
    ("디올", "레이디디올 미디움", "bag", 4_500_000, 7_500_000),
    ("셀린느", "트리옹프 미디움", "bag", 3_200_000, 5_000_000),
    ("보테가", "카세트 스몰", "bag", 2_500_000, 4_000_000),
    ("롤렉스", "서브마리너 124060", "watch", 14_000_000, 19_000_000),
    ("롤렉스", "데이트저스트 41", "watch", 11_000_000, 16_000_000),
    ("오메가", "씨마스터 300", "watch", 3_500_000, 5_500_000),
    ("까르띠에", "탱크 머스트 LM", "watch", 3_800_000, 5_800_000),
    ("까르띠에", "러브링 18K", "jewelry", 1_800_000, 2_900_000),
    ("티파니", "T와이어 브레이슬릿", "jewelry", 900_000, 1_600_000),
    ("불가리", "비제로원 반지", "jewelry", 1_400_000, 2_300_000),
    ("버버리", "트렌치코트 켄싱턴", "apparel", 900_000, 1_700_000),
    ("구찌", "GG 자카드 재킷", "apparel", 1_200_000, 2_200_000),
    ("생로랑", "스니커즈 코트클래식", "shoes", 400_000, 700_000),
    ("발렌시아가", "트리플S 스니커즈", "shoes", 500_000, 900_000),
]

CONDITIONS = ["S급", "A급", "상태 좋음", "정품 보증서 포함", "풀박스", "미사용"]

# 카테고리별 플레이스홀더 배경색. 목록에서 카테고리가 눈으로 구분된다.
CATEGORY_COLORS = {
    "bag": (61, 50, 38),
    "watch": (43, 52, 61),
    "jewelry": (74, 52, 62),
    "apparel": (48, 61, 52),
    "shoes": (61, 56, 43),
}


def _font(size: int):
    """
    크기를 지정한 기본 폰트.

    Pillow 10.1부터 load_default가 size를 받는다. 그 이전 버전은 11px 비트맵
    폰트만 주는데, 800px 캔버스에 그리면 글자가 보이지 않는다. 구버전에서도
    깨지지 않게 폴백을 둔다.
    """
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_placeholder(brand: str, model: str, category: str) -> bytes:
    """
    브랜드·모델 이름을 얹은 단색 이미지를 만든다.

    실제 제품 사진이 아니다. 명품 브랜드의 제품 사진을 생성해 붙이면 상표권 문제가
    되고, 시연에서도 "이 사진이 진짜인가"라는 질문을 부른다. 목적은 저장과 서빙
    경로를 실제로 태우는 것이므로 내용은 단순할수록 낫다. 하단에 SAMPLE 문구를
    박아 두어 화면에서도 견본임이 드러나게 한다.

    브랜드명은 영문으로 넘긴다. 컨테이너에 한글 폰트가 없으면 한글이 네모로 나온다.
    """
    width, height = 800, 1000
    background = CATEGORY_COLORS.get(category, (60, 60, 60))

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    # 가운데 얇은 테두리. 카드에서 이미지가 비어 보이지 않게 하는 최소한의 형태다.
    draw.rectangle([(90, 150), (710, 640)], outline=(255, 255, 255), width=2)
    draw.line([(90, 640), (710, 150)], fill=(255, 255, 255, 40), width=1)

    draw.text((90, 700), brand.upper(), fill=(255, 255, 255), font=_font(46))
    draw.text((90, 762), model, fill=(214, 210, 198), font=_font(30))
    draw.text((90, 812), category.upper(), fill=(170, 166, 154), font=_font(22))
    draw.text(
        (90, 900),
        "SAMPLE IMAGE - NOT A REAL PHOTO",
        fill=(150, 146, 136),
        font=_font(20),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()


# 브랜드 영문 표기. 기본 폰트가 한글을 못 그려서 이미지에는 영문을 쓴다.
BRAND_LATIN = {
    "샤넬": "Chanel", "루이비통": "Louis Vuitton", "구찌": "Gucci",
    "에르메스": "Hermes", "프라다": "Prada", "디올": "Dior",
    "셀린느": "Celine", "보테가": "Bottega Veneta", "롤렉스": "Rolex",
    "오메가": "Omega", "까르띠에": "Cartier", "티파니": "Tiffany",
    "불가리": "Bulgari", "버버리": "Burberry", "생로랑": "Saint Laurent",
    "발렌시아가": "Balenciaga",
}


async def seed() -> None:
    async with async_session() as session:
        seller_ids: list[int] = []

        for spec in SELLERS:
            spec = {**spec, "business_number": normalize_business_number(spec["business_number"])}

            check = check_seller(
                name=spec["name"],
                business_number=spec["business_number"],
                phone=spec["phone"],
                has_store=spec["has_store"],
                address=spec["address"],
                latitude=spec["latitude"],
                longitude=spec["longitude"],
            )

            # 시드 데이터도 실제 등록과 같은 검사를 통과해야 한다. 여기를 건너뛰면
            # 화면에서만 보이는 데이터와 API로 들어오는 데이터의 규칙이 갈라진다.
            if not check.ok:
                raise ValueError(f"{spec['name']}: {' / '.join(check.reasons)}")

            existing = (
                await session.execute(
                    select(Seller).where(Seller.business_number == spec["business_number"])
                )
            ).scalar_one_or_none()

            if existing is not None:
                seller_ids.append(existing.id)
                continue

            seller = Seller(**spec)
            session.add(seller)
            await session.flush()
            seller_ids.append(seller.id)
            logger.info("판매자 추가: %s (id=%s)", seller.name, seller.id)

        await session.commit()

        # ── 매물 ────────────────────────────────────────────────────
        created = 0
        authenticated = 0

        for index in range(60):
            brand, model, category, low, high = CATALOG[index % len(CATALOG)]
            seller_id = seller_ids[index % len(seller_ids)]
            url = f"https://demo.reverdi.local/items/{index + 1:04d}"

            existing = (
                await session.execute(select(ItemRecord).where(ItemRecord.url == url))
            ).scalar_one_or_none()

            if existing is not None:
                continue

            # 정품 인증은 40%. 같은 판매자 안에서도 섞이게 둔다 — 뱃지가 "이 업자는
            # 전부 인증"이 아니라 "증표를 확인한 물건만 인증"을 뜻해야 하기 때문이다.
            is_authenticated = RNG.random() < 0.40
            price_value = RNG.randrange(low, high, 10_000)
            condition = RNG.choice(CONDITIONS)
            title = f"{brand} {model} {condition}"

            raw = make_placeholder(BRAND_LATIN.get(brand, brand), model, category)

            # 시드 이미지도 업로드와 같은 검증·재인코딩을 거친다. 저장 경로가 실제로
            # 동작하는지 확인하는 것이 이 시드의 목적 중 하나다.
            safe = sanitize_image(raw)
            object_name = save_image(safe.data, safe.extension)

            session.add(
                ItemRecord(
                    source=SOURCE,
                    brand=brand,
                    search_brand=brand,
                    clean_title=title,
                    category=category,
                    title=title,
                    price=f"{price_value:,}원",
                    price_value=price_value,
                    region=None,
                    time_text=None,
                    image_url=public_url(object_name),
                    url=url,
                    is_sold=False,
                    seller_id=seller_id,
                    is_authenticated=is_authenticated,
                    is_usable=True,
                    is_active=True,
                )
            )

            created += 1
            authenticated += int(is_authenticated)

        await session.commit()

    logger.info(
        "매물 %d건 추가 (정품인증 %d건 / 미인증 %d건)",
        created,
        authenticated,
        created - authenticated,
    )
    logger.info("판매자 %d명", len(seller_ids))


if __name__ == "__main__":
    asyncio.run(seed())
