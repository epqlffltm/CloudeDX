# app/tests/test_cleaning.py

"""
제목 정제 파이프라인 테스트.

여기 있는 케이스는 대부분 **실제 수집 데이터 599건에서 가져왔다.** 지어낸 예시로
규칙을 만들면 실제로 안 나오는 상황을 방어하고 자주 나오는 상황을 놓친다.

정제가 틀리면 시세가 통째로 무너진다. 브랜드가 어긋나면 "루이비통 최저가"에 구찌
가격이 섞이고, 가방이 아닌 상품이 섞이면 카드지갑 가격이 가방 최저가가 된다.
"""

import pytest

from app.domain.brands import (
    detect_brand,
    detect_brand_with_model_hint,
    is_target_brand,
    strip_spam_tail,
)
from app.domain.cleaning import clean_title
from app.domain.product_type import find_model, is_bag

# ---------------------------------------------------------------------------
# 스팸 꼬리 절단
# ---------------------------------------------------------------------------


def test_strips_brand_listing_tail():
    """
    셀러가 검색 노출을 위해 붙이는 브랜드 나열. 실측 599건 중 15%에 있었다.
    """
    title = "구찌 홀스빗 크로스백/숄더백 새상품급 정품(감정O)프라다루이비통디올고야드샤넬셀린느보테가"

    assert strip_spam_tail(title) == "구찌 홀스빗 크로스백/숄더백 새상품급 정품(감정O"


def test_does_not_erase_the_whole_title():
    """
    상품명 자체에 브랜드가 들어가므로 위치 0부터 자르면 제목이 사라진다.
    처음 구현했을 때 실제로 빈 문자열이 나오는 버그가 있었다.
    """
    title = "구찌 스네이크 클러치백 정품A급구찌프라다루이비통디올고야드샤넬"
    result = strip_spam_tail(title)

    assert result.startswith("구찌 스네이크")
    assert len(result) > 6


def test_normal_title_is_untouched():
    title = "샤넬 클래식 캐비어 클러치백 라지 그린"

    assert strip_spam_tail(title) == title


def test_few_brand_mentions_are_not_spam():
    """
    브랜드 두 개는 정상적인 제목일 수 있다 — "샤넬 교환 가능" 같은 문구.
    임계값을 3으로 둔 이유다.
    """
    title = "샤넬 코코핸들 쉐브론 블랙 미듐 - 샤넬 교환도 가능"

    assert strip_spam_tail(title) == title


# ---------------------------------------------------------------------------
# 브랜드 판정
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("샤넬 클래식 플랩 미디움", "샤넬"),
        ("구찌 마몬트 미니 체인백", "구찌"),
        ("루이비통 네오노에 가방", "루이비통"),
        ("루이뷔통 페이보릿 PM 가방", "루이비통"),  # 실측에 나온 표기 변형
        ("에르메스 켈리 25 로즈아잘레", "에르메스"),
        ("GUCCI 구찌 오피디아 더플백", "구찌"),
    ],
)
def test_detects_brand(title, expected):
    assert detect_brand(title) == expected


def test_first_brand_wins():
    """
    실측 92건의 스팸 제목을 확인한 결과, 상품명이 앞에 오고 검색용 나열이 뒤에
    붙는 규칙이 어긋난 경우가 없었다.
    """
    title = "구찌 마몽 마틀라세 스몰 크로스백 정품S급(감정O)프라다루이비통디올고야드샤넬"

    assert detect_brand(title) == "구찌"


def test_detects_non_target_brand():
    """
    대상 외 브랜드를 판정할 수 있어야 걸러낼 수 있다. 이 사전이 없으면
    "루이비통으로 저장된 발렌시아가"를 잡지 못한다.
    """
    title = "발렌시아가 시티 모터백 스몰 크로스백 정품S급구찌프라다루이비통디올"
    brand = detect_brand(title)

    assert brand == "발렌시아가"
    assert is_target_brand(brand) is False


def test_infers_brand_from_model_name():
    """
    셀러가 브랜드를 생략하고 모델명만 쓰는 경우. 실측에 두 건 있었다.
    """
    assert detect_brand_with_model_hint("클래식 미듐 핑크 은장") == "샤넬"
    assert detect_brand_with_model_hint("GG마몽 마틀라쎄 미디엄 체인숄더백") == "구찌"


def test_gives_up_when_nothing_matches():
    assert detect_brand_with_model_hint("명품 쇼핑백") is None
    assert detect_brand_with_model_hint("안심결제") is None


# ---------------------------------------------------------------------------
# 가방 판정
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "샤넬 클래식 캐비어 클러치백 라지 그린",
        "구찌 GG 마몬트 탑핸들백 블랙",
        "루이비통 네오노에 가방",
        "구찌 GG 슈프림 벨트백 블랙",  # 벨트백은 가방이다
        "구찌 남녀공용가방 GG 패턴 힙색 메신저 크로스백",
    ],
)
def test_accepts_bags(title):
    assert is_bag(title)[0] is True


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("샤넬 코코 마드모아젤 오 드 빠르펭 향수 100ml", "향수"),
        ("에르메스 제트 스니커즈 블랙 39.5", "스니커즈"),
        ("샤넬 24C 크루즈 자켓 36", "자켓"),
        ("구찌 인터로킹 펜던트 목걸이 (실버)", "목걸이"),
        ("에르메스 쇼핑백 4종 세트", "쇼핑백"),
        ("루이비통 종이가방 쇼핑백 360*250*110", "쇼핑백"),
        ("구찌 GG 엠블럼 반지갑 (새상품)", "반지갑"),
        ("루이비통 가방 스트랩- 보증서 유", "스트랩"),
    ],
)
def test_rejects_non_bags(title, reason):
    """실측에서 나온 오염 사례. 24%가 이런 것들이었다."""
    ok, why = is_bag(title)

    assert ok is False
    assert why == reason


def test_accessory_check_comes_before_bag_words():
    """
    "가방 스트랩"에는 "가방"이 들어 있다. 순서가 틀리면 부속품이 가방으로 잡힌다.
    """
    ok, why = is_bag("정품 루이비통 숄더백 크로스백 가방 스트랩 블랙")

    assert ok is False
    assert why == "스트랩"


def test_model_name_alone_is_enough():
    """
    "백/가방" 단어 없이 모델명만 쓰는 제목이 많다. 모델 사전이 없으면 이런
    진짜 가방이 전부 제외된다 — 실측에서 20건 넘게 살아났다.
    """
    for title in ["샤넬 뉴미니 블랙 램스킨", "샤넬 2.55 빈티지 라지", "샤넬 클래식 WOC 블랙 금장"]:
        assert is_bag(title, "샤넬")[0] is True, title


# ---------------------------------------------------------------------------
# 모델 추출
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "brand", "expected"),
    [
        ("구찌 마몬트 미니 체인백", "구찌", "마몬트"),
        ("구찌 GG 마몽 숄더백 아이보리", "구찌", "마몬트"),  # 표기 통일
        ("구찌 패들락 탑핸들", "구찌", "패드락"),
        ("샤넬 2.55 빈티지 라지", "샤넬", "2.55"),
        ("샤넬 19백 블랙 미디움 금장", "샤넬", "19"),
        ("구찌실비백", "구찌", "실비"),  # 띄어쓰기 없는 표기
        ("구찌홀스빗1955탑핸들", "구찌", "홀스빗"),
    ],
)
def test_extracts_model(title, brand, expected):
    assert find_model(title, brand) == expected


def test_patterns_are_not_models():
    """
    루이비통의 "모노그램"과 "다미에"는 캔버스 무늬이지 모델이 아니다. 같은 무늬로
    여러 모델이 나오므로, 모델로 잡으면 서로 다른 가방이 한 덩어리가 된다.
    실측에서 "모노그램 28건"이 최상위로 올라왔던 오류다.
    """
    assert find_model("루이비통 모노그램 숄더백", "루이비통") is None
    assert find_model("루이비통 다미에 그라파이트 브리프케이스", "루이비통") is None


def test_prefers_longer_model_name():
    """"19백"과 "19"가 모두 사전에 있을 때 짧은 쪽이 먼저 걸리면 안 된다."""
    assert find_model("샤넬 19백 미디움", "샤넬") == "19"


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------


def test_clean_title_on_good_item():
    result = clean_title("샤넬 클래식 캐비어 클러치백 라지 그린")

    assert result.is_usable is True
    assert result.brand == "샤넬"
    assert result.model == "클래식"
    assert result.reject_reason is None


def test_clean_title_corrects_brand():
    """
    실측에서 가장 많았던 교정: 루이비통으로 저장된 구찌 31건.
    """
    title = "구찌 스네이크 클러치백 정품A급(영수증O)구찌프라다루이비통디올고야드샤넬셀린느"
    result = clean_title(title, search_brand="루이비통")

    assert result.is_usable is True
    assert result.brand == "구찌"


def test_clean_title_rejects_other_brand():
    title = "메종 마르지엘라 버킷백 정품S급구찌프라다루이비통디올고야드샤넬"
    result = clean_title(title)

    assert result.is_usable is False
    assert "대상 외 브랜드" in result.reject_reason


def test_clean_title_keeps_original():
    """
    판정이 틀릴 수 있고 규칙을 고쳤을 때 재판정해야 하므로 원본을 버리지 않는다.
    """
    title = "구찌 마몬트 크로스백 정품구찌프라다루이비통디올고야드샤넬"
    result = clean_title(title)

    assert result.raw_title == title
    assert result.clean_title != title
    assert result.display_title == result.clean_title