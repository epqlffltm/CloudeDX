#app/crawler/.py

"""
크롤러
"""

import time
from urllib.parse import urlencode

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.crawler.browser import create_chrome_driver
from app.crawler.config import CrawlerConfig
from app.crawler.models import CrawledItem
from app.crawler.parser import is_item_detail_url, parse_anchor


class DaangnCrawler:
    """
    당근 중고거래 검색 결과 크롤러.

    책임:
    1. 검색 URL 생성
    2. 브라우저 실행
    3. 스크롤로 검색 결과 로딩
    4. 매물 카드 수집/파싱
    5. 중복 제거 후 CrawledItem 목록 반환

    DB 저장은 여기서 하지 않는다.
    """

    ITEM_LINK_SELECTOR = "a[href*='/kr/buy-sell/']"

    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()

    def build_search_url(
        self,
        query: str,
        *,
        region_code: str | None = None,
    ) -> str:
        query = query.strip()

        if not query:
            raise ValueError("검색어(query)는 비어 있을 수 없습니다.")

        params = {"search": query}

        # 당근 검색 URL의 in 파라미터는 사람이 읽는 '강남구'가 아니라
        # 예: '성수동2가-6141' 같은 지역 코드/slug 형태다.
        if region_code:
            params["in"] = region_code.strip()

        return f"{self.config.base_url}?{urlencode(params)}"

    def _detail_link_count(self, driver) -> int:
        anchors = driver.find_elements(By.CSS_SELECTOR, self.ITEM_LINK_SELECTOR)

        count = 0
        for anchor in anchors:
            try:
                if is_item_detail_url(anchor.get_attribute("href")):
                    count += 1
            except Exception:
                continue

        return count

    def _wait_for_initial_page(self, driver) -> None:
        """
        매물 링크가 나타나거나, 검색 결과 없음 문구가 나타날 때까지 기다린다.
        결과가 0건이어도 정상 종료할 수 있도록 한다.
        """

        def page_ready(d):
            if self._detail_link_count(d) > 0:
                return True

            page_text = d.find_element(By.TAG_NAME, "body").text
            no_result_markers = (
                "게시글이 없어요",
                "검색 결과가 없어요",
                "검색어를 수정",
            )
            return any(marker in page_text for marker in no_result_markers)

        try:
            WebDriverWait(
                driver,
                self.config.timeout_seconds,
            ).until(page_ready)
        except TimeoutException:
            # 사이트가 느리거나 구조가 바뀌어도 여기서 즉시 죽이지 않고,
            # 현재 DOM에 있는 링크를 한 번 더 수집해 본다.
            pass

    def _scroll_results(self, driver) -> None:
        previous_count = self._detail_link_count(driver)
        stable_rounds = 0

        for _ in range(self.config.scroll_count):
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(self.config.scroll_pause_seconds)

            current_count = self._detail_link_count(driver)

            if current_count <= previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            previous_count = current_count

            # 두 번 연속 새 링크가 없으면 더 스크롤하지 않는다.
            if stable_rounds >= 2:
                break

    def _collect_items(self, driver) -> list[CrawledItem]:
        anchors = driver.find_elements(By.CSS_SELECTOR, self.ITEM_LINK_SELECTOR)

        unique_items: dict[str, CrawledItem] = {}

        for anchor in anchors:
            item = parse_anchor(anchor)

            if item is None:
                continue

            # 상세 URL을 고유키처럼 사용한다.
            unique_items[item.url] = item

        return list(unique_items.values())

    def crawl(
        self,
        query: str,
        *,
        region_code: str | None = None,
    ) -> list[CrawledItem]:
        url = self.build_search_url(
            query,
            region_code=region_code,
        )

        driver = create_chrome_driver(self.config)

        try:
            driver.get(url)
            self._wait_for_initial_page(driver)
            self._scroll_results(driver)
            return self._collect_items(driver)
        finally:
            driver.quit()
