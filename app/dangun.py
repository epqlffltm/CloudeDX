from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
import random

def crawl_daangn_with_images(search_query, region_name=None):
    chrome_options = Options()
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    # `--headless`를 추가하여 브라우저 창 없이 실행할 수 있으나, 디버깅을 위해 주석 처리합니다.
    # chrome_options.add_argument('--headless')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    # 자동화 방지 변수 제거
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })

    try:
        if region_name:
            print(f"'{region_name}' 지역에서 '{search_query}' 매물 수집을 시도합니다.")
            driver.get("https://www.daangn.com/")
            time.sleep(random.uniform(3, 5))

            try:
                # 1. 지역 선택 버튼 클릭 시도 (예: '.header-top-region' 클래스를 가진 요소)
                # 이 셀렉터는 웹사이트 변경에 따라 달라질 수 있습니다.
                region_select_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '.header-top-region'))
                )
                region_select_button.click()
                print(f"지역 선택 버튼 클릭 시도... (타겟 지역: {region_name})")
                time.sleep(random.uniform(2, 4))

                # 2. 지역 검색 입력 필드에 지역명 입력
                # 모달 내의 입력 필드를 찾아야 합니다. 이 셀렉터는 변경될 수 있습니다.
                region_search_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='동네 검색']"))
                )
                region_search_input.send_keys(region_name)
                print(f"지역 검색 필드에 '{region_name}' 입력")
                time.sleep(random.uniform(2, 4))

                # 3. 검색된 지역 결과 중 첫 번째 항목 클릭
                # 보통 검색 결과는 목록으로 표시되며, 해당 지역 이름을 포함하는 항목을 찾습니다.
                # 정확한 셀렉터는 웹사이트 구조에 따라 달라집니다.
                first_region_result = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, f"//li[contains(@class, 'region-search-result-item')]//span[contains(text(), '{region_name}')]")) # 좀 더 유연하게 조정 필요
                )
                first_region_result.click()
                print(f"'{region_name}' 지역 선택 완료")
                time.sleep(random.uniform(3, 5))

            except Exception as e:
                print(f"지역 변경 중 오류 발생 (이는 웹사이트 구조 변경 때문일 수 있습니다): {e}")
                print("기본 지역 또는 검색 URL로 계속 진행합니다. 수동으로 셀렉터를 확인하고 수정해야 할 수 있습니다.")
                # 지역 변경 실패 시에도 크롤링은 진행하기 위해 계속 진행

            # 지역 변경 후, 검색 페이지로 이동
            url = f"https://www.daangn.com/search/{search_query}"
            driver.get(url)
            print(f"'{search_query}' 검색 페이지로 이동합니다.")
            time.sleep(random.uniform(3, 5))

        else: # region_name이 없을 경우 기존 로직 유지 (전체 검색)
            url = f"https://www.daangn.com/search/{search_query}"
            driver.get(url)
            print(f"당근마켓 이미지 포함 매물 수집 중 (기본 지역): {url}")
            time.sleep(5)

        # 동적 로딩을 위해 스크롤을 한 번 수행 (또는 여러 번)
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(2)

        all_links = driver.find_elements(By.TAG_NAME, 'a')

        data = []
        for link in all_links:
            href = link.get_attribute('href')
            if not href: continue

            if '/buy-sell/' in href and '?search=' not in href and '?category=' not in href and 'in=' not in href:
                text_content = link.text.strip()
                if text_content:
                    lines = [l.strip() for l in text_content.split('\n') if l.strip() and l.strip() != '·']

                    # 이미지 추출 시도
                    try:
                        img_element = link.find_element(By.TAG_NAME, 'img')
                        img_url = img_element.get_attribute('src')
                    except:
                        img_url = "이미지 없음"

                    # 데이터 파싱 로직 (기존과 동일하지만 지역 파싱은 좀 더 일반화)
                    if len(lines) >= 3:
                        title = lines[0]
                        price = "정보없음"
                        extracted_region = "정보없음" # 'region'과 겹치지 않게 이름 변경
                        time_info = "정보없음"

                        # 가격 정보 파싱
                        for line in lines:
                            if '원' in line: 
                                price = line
                                break
                        # 지역 정보 파싱 (가격, 시간, 제목이 아닌 짧은 문자열)
                        # 이 부분은 웹사이트 구조에 따라 더 정확한 CSS Selector나 XPath를 사용하는 것이 좋습니다.
                        # 여기서는 text_content에서 유추하는 방식으로 시도합니다.
                        filtered_lines = [l for l in lines if l != title and '원' not in l and '전' not in l and '끌올' not in l and l != '정보없음']
                        if filtered_lines:
                            extracted_region = filtered_lines[0] # 첫 번째 필터링된 라인을 지역으로 가정

                        # 시간 정보 파싱
                        if '전' in lines[-1]:
                            time_info = lines[-1]

                        data.append({
                            '제목': title,
                            '가격': price,
                            '지역': extracted_region, # 파싱된 지역 사용
                            '시간': time_info,
                            '이미지링크': img_url,
                            '링크': href
                        })

        return pd.DataFrame(data)

    finally:
        driver.quit()

# 실행
print("이미지 포함 매물 데이터 수집을 시작합니다...")
# -------------------- 일반 검색 예시 (기존과 동일) --------------------
search_item_global = '샤넬 가방'
final_img_df_global = crawl_daangn_with_images(search_item_global)

if not final_img_df_global.empty:
    final_img_df_global = final_img_df_global.drop_duplicates(subset=['링크']).reset_index(drop=True)
    print(f"\n--- 수집 완료 (기본 지역: '{search_item_global}'): 총 {len(final_img_df_global)}건 (이미지 포함) ---")
    print(final_img_df_global[['제목', '가격', '지역', '이미지링크']].head(5))
    final_img_df_global.to_csv(f'daangn_global_{search_item_global.replace(" ", "_")}_with_images.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과가 'daangn_global_{search_item_global.replace(" ", "_")}_with_images.csv' 파일로 저장되었습니다.")
else:
    print(f"\n기본 지역에서 '{search_item_global}' 데이터를 찾지 못했습니다.")

print("\n-------------------------------------\n")

# -------------------- 다른 지역 검색 예시 --------------------
region_to_crawl = '강남구' # 원하는 지역으로 변경하세요
search_item_region = '아이폰' # 원하는 검색어로 변경하세요
final_img_df_region = crawl_daangn_with_images(search_item_region, region_to_crawl)

if not final_img_df_region.empty:
    final_img_df_region = final_img_df_region.drop_duplicates(subset=['링크']).reset_index(drop=True)
    print(f"\n--- 수집 완료 ('{region_to_crawl}' 지역: '{search_item_region}'): 총 {len(final_img_df_region)}건 (이미지 포함) ---")
    print(final_img_df_region[['제목', '가격', '지역', '이미지링크']].head(5))
    final_img_df_region.to_csv(f'daangn_{region_to_crawl}_{search_item_region.replace(" ", "_")}_with_images.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과가 'daangn_{region_to_crawl}_{search_item_region.replace(" ", "_")}_with_images.csv' 파일로 저장되었습니다.")
else:
    print(f"\n'{region_to_crawl}' 지역에서 '{search_item_region}' 데이터를 찾지 못했습니다. (사이트 구조 변경 또는 지역 변경 실패 가능성)")
