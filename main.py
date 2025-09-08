from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

import argparse, sys, time, os, re
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

# ==========================
# Helpers: parsing functions
# ==========================
def parse_count(text: str) -> int:
    """แปลง '(36)', '1.2k', '3K', '2.5M', '12,345' -> int"""
    if not text:
        return 0
    t = text.strip().strip("()").replace(",", "").lower()
    m = re.match(r'^([0-9]*\.?[0-9]+)\s*([km])?$', t)
    if m:
        num = float(m.group(1))
        suffix = m.group(2)
        if suffix == 'k':
            return int(num * 1_000)
        if suffix == 'm':
            return int(num * 1_000_000)
        return int(num)
    digits = re.sub(r'\D', '', t)
    return int(digits) if digits else 0

def parse_sold(text: str) -> int:
    """แปลง '138 sold', '9 Sold', 'N/A' -> int (ไม่มีข้อมูล = 0)"""
    if not text:
        return 0
    digits = re.sub(r'\D', '', text)
    return int(digits) if digits else 0

# ==========================
# CLI arguments
# ==========================
parser = argparse.ArgumentParser(description="Lazada scraper")
parser.add_argument("--query", "-q", type=str, help="คำค้นหาสินค้า")
parser.add_argument("--pages", "-p", type=int, default=2, help="จำนวนหน้าที่จะดึง (ค่าเริ่มต้น 2)")
args = parser.parse_args()

def get_search_text():
    if args.query:
        return " ".join(args.query.split())  # normalize ช่องว่างซ้ำ
    if sys.stdin.isatty():
        try:
            txt = input("พิมพ์คำค้นหาสินค้า: ").strip()
            if txt:
                return " ".join(txt.split())
        except EOFError:
            pass
    raise SystemExit('ไม่พบคำค้นหา: โปรดส่ง --query "คำค้น" หรือพิมพ์ในคอนโซล')

search_text = get_search_text()
target = int(input("กี่ข้อมูล : "))
# ประมาณการ ~40 การ์ด/หน้า แล้วเคารพ --pages ที่อาจส่งมา
auto_pages = max(1, (target + 39) // 40)  # ceil(target/40)
pages = max(auto_pages, int(args.pages))
print(f"[INFO] จะค้นหา: {search_text} | หน้าที่ดึง: {pages} | เป้าหมาย {target} ชิ้น")

# ==========================
# WebDriver (ลด log กวนตา)
# ==========================
options = webdriver.ChromeOptions()
options.add_experimental_option("detach", True)
options.add_argument("--log-level=3")
options.add_argument("--disable-logging")
options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)
wait = WebDriverWait(driver, 20)

# ==========================
# Open site & search
# ==========================
driver.get("https://www.lazada.co.th/#?")
time.sleep(3)

try:
    search_box = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="q"]')))
    search_box.clear()
    search_box.send_keys(search_text)

    # กดปุ่มค้นหา ถ้าไม่เจอให้กด Enter แทน
    try:
        search_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="topActionHeader"]/div/div[2]/div/div[2]/div/form/div/div[2]/a'))
        )
        search_btn.click()
    except Exception:
        search_box.send_keys(Keys.ENTER)

    # รอให้มีการ์ด (จะรอแบบ union ได้ ไม่กระทบการนับ)
    wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.buTCk, div[data-qa-locator='product-item']")))
    print("On product search")
except Exception as e:
    driver.quit()
    raise SystemExit(f"Error details (search): {e}")

# ==========================
# Card picker (แก้ปัญหานับซ้ำ)
# ==========================
def pick_cards(soup):
    cards = soup.select('div[data-qa-locator="product-item"]')
    if not cards:
        cards = soup.select('div.buTCk')
    return cards

# ==========================
# Pagination helper
# ==========================
def click_next_or_stop(driver, timeout=15) -> bool:
    w = WebDriverWait(driver, timeout)
    # เลื่อนลงให้ pagination โผล่
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(0.8)

    # ถ้า next disabled → จบ
    disabled = driver.find_elements(By.CSS_SELECTOR, "li.ant-pagination-next.ant-pagination-disabled")
    if disabled:
        print("Reached last page (Next disabled).")
        return False

    # หา next หลายรูปแบบ
    selectors = [
        'li.ant-pagination-next:not(.ant-pagination-disabled) button',
        'li.ant-pagination-next:not(.ant-pagination-disabled) a',
        'button[aria-label="Next Page"]',
        'li[title="Next Page"] button',
        'a.ant-pagination-item-link[aria-label="Next Page"]',
    ]
    next_el = None
    for sel in selectors:
        try:
            next_el = w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            if next_el:
                break
        except Exception:
            continue
    if not next_el:
        print("Next button not found. Stop.")
        return False

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_el)
    time.sleep(0.2)
    try:
        next_el.click()
    except Exception:
        try:
            ActionChains(driver).move_to_element(next_el).click().perform()
        except Exception as e:
            print(f"Click next failed: {e}")
            return False

    # รอการ์ดสินค้าโผล่ (หน้าถัดไป)
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.buTCk, div[data-qa-locator='product-item']")))
    except Exception:
        pass
    return True

# ==========================
# Scroll helper (โหลดการ์ดให้ครบก่อนอ่าน HTML)
# ==========================
def lazy_scroll_until_stable(max_rounds=12, patience=3):
    """
    เลื่อนลงเป็นช่วง ๆ จนจำนวนการ์ดไม่เพิ่มต่อเนื่อง 'patience' ครั้ง หรือครบ max_rounds
    """
    last_count = 0
    stable_ticks = 0
    for _ in range(max_rounds):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight*0.6);")
        time.sleep(0.7)
        sp = BeautifulSoup(driver.page_source, "html.parser")
        cur = len(pick_cards(sp))
        if cur <= last_count:
            stable_ticks += 1
        else:
            stable_ticks = 0
            last_count = cur
        if stable_ticks >= patience:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            break

# ==========================
# Scrape loop
# ==========================
all_inform = []
seen_urls = set()  # กันซ้ำเบา ๆ ด้วย URL (ไม่เขียนลง CSV)

for page_i in range(1, pages + 1):
    print(f"Start scraping page {page_i}")
    time.sleep(1.0)

    # เลื่อนให้โหลดการ์ดครบก่อน
    lazy_scroll_until_stable(max_rounds=12, patience=3)

    data = driver.page_source
    soup = BeautifulSoup(data, "html.parser")

    # ใช้ fallback ไม่ใช่ union (กันนับซ้ำ)
    cards = pick_cards(soup)
    print(f"Column product: {len(cards)}")

    for p in cards:
        # defaults
        product_name = 'N/A'
        product_price = 'N/A'
        product_sold = 0
        product_location = 'N/A'
        is_lazmall = 'No'
        reviews = 0

        # URL เพื่อกันซ้ำ
        url = None
        a = p.find("a", href=True)
        if a and a['href']:
            href = a['href']
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://www.lazada.co.th" + href
            url = href
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        name_el = p.find("div", {"class": "RfADt"})
        if name_el:
            product_name = name_el.get_text(strip=True)

        price_el = p.find("span", {"class": "ooOxS"})
        if price_el:
            product_price = price_el.get_text(strip=True)

        sold_el = p.find("span", {"class": "_1cEkb"}) or p.find("span", string=re.compile(r"[Ss]old"))
        product_sold = parse_sold(sold_el.get_text(strip=True) if sold_el else "")

        loc_el = p.find("span", {"class": "oa6ri"})
        if loc_el:
            product_location = loc_el.get_text(strip=True)

        # LazMall badge
        badge_el = p.select_one("i.ic-dynamic-badge-68959")
        is_lazmall = "Yes" if badge_el else "No"

        # Reviews
        rv_el = p.select_one("span.qzqFw") or p.find("span", string=re.compile(r"\(\s*\d"))
        if rv_el:
            reviews = parse_count(rv_el.get_text(strip=True))

        all_inform.append([
            product_name, product_price, product_sold,
            product_location, is_lazmall, reviews
        ])

        # หยุดเมื่อครบเป้า
        if len(all_inform) >= target:
            break

    # ออกจาก loop หน้านี้ถ้าครบเป้าแล้ว
    if len(all_inform) >= target:
        break

    # ไปหน้าถัดไป
    if page_i < pages:
        if not click_next_or_stop(driver):
            break

# ==========================
# Save CSV
# ==========================
df = pd.DataFrame(
    all_inform,
    columns=["Product", "Price", "Sold", "Location", "LazMall", "Reviews"]
)
print(df.head())

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"lazadareport_{timestamp}.csv"
df.to_csv(filename, index=False, encoding="utf-8-sig")
print(f"Create CSV file successfully: {os.path.abspath(filename)}")

# ปิดเบราว์เซอร์ถ้าไม่ต้องดูต่อ
# driver.quit()
