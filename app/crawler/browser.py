#app/crawler/browser.py

"""
Chrome 생성만 담당
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from app.crawler.config import CrawlerConfig


def create_chrome_driver(config: CrawlerConfig) -> webdriver.Chrome:
    """
    Selenium Chrome 드라이버 생성.

    Selenium 4의 Selenium Manager를 사용하므로
    webdriver-manager를 코드에서 직접 호출하지 않는다.
    """

    options = Options()
    options.page_load_strategy = "eager"

    if config.headless:
        options.add_argument("--headless=new")

    options.add_argument(
        f"--window-size={config.window_width},{config.window_height}"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=ko-KR")
    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"],
    )
    options.add_experimental_option(
        "useAutomationExtension",
        False,
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(config.timeout_seconds)

    # navigator.webdriver 값을 숨기는 최소 설정.
    # 사이트 정책/구조 변경에 따라 언제든 동작이 달라질 수 있다.
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )

    return driver
