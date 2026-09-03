# app/domain/ownership.py

"""
"이 매물을 이 계정이 고쳐도 되는가"의 한 가지 규칙.

CSV 업로드와 사진 등록이 같은 판단을 해야 한다. 두 곳에 따로 적으면 한쪽만
고쳐지는 사고가 난다 — 실제로 사진 등록에는 출처 검사가 있었는데 CSV upsert에는
없어서, 크롤링 매물의 URL을 CSV에 적으면 그 매물이 통째로 덮이고 출처까지
'직접등록'으로 바뀌었다.

규칙은 둘뿐이다.
    1. 출처가 직접등록(UPLOAD)이 아니면 누구의 것도 아니다 — 원문 사이트의 매물이다.
    2. 매물의 판매자와 계정의 판매자가 **같아야** 한다. 어느 한쪽이 None 이면 아니다.

"판매자 연결이 없는 업로드 매물은 client 면 고칠 수 있다"는 예외를 **두지 않는다.**
지금은 client 계정이 하나라 그 예외가 무해해 보이지만, 판매자별 계정이 생기는
순간 "주인 없는 매물은 아무나 고친다"가 된다. 그때 고치려면 이 파일을 기억해야
하는데, 아무도 기억하지 못한다. 처음부터 엄격하게 두고, 주인 없는 매물이 생기지
않게 하는 쪽(업로드 시 연결)이 맞다.

계정의 판매자 id 는 User.seller_id 로 온다. 설정에서 오든 DB 에서 오든 여기서는 모른다.
"""

from app.domain.sources import UPLOAD


def owns_item(
    *,
    account_seller_id: int | None,
    item_source: str,
    item_seller_id: int | None,
) -> bool:
    """account_seller_id 로 선언된 계정이 이 매물을 고쳐도 되는지."""
    if item_source != UPLOAD:
        return False

    if account_seller_id is None or item_seller_id is None:
        return False

    return item_seller_id == account_seller_id
