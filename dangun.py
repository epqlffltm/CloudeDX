from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time

def crawl_daangn_with_images(search_query):
    chrome_options = Options()
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        url = f"https://www.daangn.com/search/{search_query}"
        driver.get(url)
        print(f"당근마켓 이미지 포함 매물 수집 중: {url}")
        time.sleep(5)

        # 동적 로딩을 위해 스크롤을 한 번 수행
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

                    if len(lines) >= 3:
                        data.append({
                            '제목': lines[0],
                            '가격': lines[1] if '원' in lines[1] else (lines[2] if '원' in lines[2] else "정보없음"),
                            '지역': next((l for l in lines if not any(c in l for c in ['원', '전', '끌올'])), "정보없음"),
                            '시간': lines[-1] if '전' in lines[-1] else "정보없음",
                            '이미지링크': img_url,
                            '링크': href
                        })

        return pd.DataFrame(data)

    finally:
        driver.quit()

# 실행
print("이미지 포함 매물 데이터 수집을 시작합니다...")
final_img_df = crawl_daangn_with_images('샤넬 가방')

if not final_img_df.empty:
    final_img_df = final_img_df.drop_duplicates(subset=['링크']).reset_index(drop=True)
    
    print(f"\n--- 수집 완료: 총 {len(final_img_df)}건 (이미지 포함) ---")
    print(final_img_df[['제목', '가격', '이미지링크']].head(10))
    
    final_img_df.to_csv('daangn_with_images.csv', index=False, encoding='utf-8-sig')
    print("\n결과가 'daangn_with_images.csv' 파일로 저장되었습니다.")
else:
    print("\n데이터를 찾지 못했습니다.")
