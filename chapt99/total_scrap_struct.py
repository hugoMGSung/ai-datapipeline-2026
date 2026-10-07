"""다나와 게이밍 PC 10페이지 수집 및 CSV/PostgreSQL 저장 스크립트.

필요 패키지: selenium, pandas, sqlalchemy, psycopg[binary]
"""

import logging
import os
import re
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from sqlalchemy import BigInteger, Integer, Text, URL, create_engine

# 작업 디렉터리 아래 data 폴더에 CSV와 로그를 저장합니다.
DATA_DIR = Path.cwd() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TODAY = datetime.now()
CSV_FILE = DATA_DIR / f"danawa_게이밍PC_{TODAY:%Y%m%d}.csv"
LOG_FILE = DATA_DIR / "scraping.log"
PAGE_URL = "https://prod.danawa.com/list/?cate=11255834&15main_11_02"
PRODUCT_SELECTOR = 'div[data-testid="ProductListItem"]'
PAGER_SELECTOR = "nav > nav div button"
WAIT_SECONDS = 10
PAGE_COUNT = 10
PRODUCTS_PER_PAGE = 90

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("danawa_scraper")

def parse_price(price_text):
    """쉼표가 있는 가격 문자열을 정수로 바꾸고, 변환에 실패하면 None을 반환합니다."""
    if not price_text:
        return None
    digits = re.sub(r"[^0-9]", "", price_text)
    return int(digits) if digits else None


def collect_product(product, page_num, item_index):
    """상품 카드 하나를 읽습니다. 상품 일부가 잘못되어도 전체 수집은 계속합니다."""
    try:
        sections = product.find_elements(By.CSS_SELECTOR, ".dnw-product-list-item > div")
        if len(sections) < 3:
            logger.warning("상품 영역 누락: 페이지 %d, 순번 %d", page_num, item_index)
            return None

        computer_info = sections[1]
        price_info = sections[2]
        name_elements = computer_info.find_elements(By.CSS_SELECTOR, "div a")
        computer_name = name_elements[0].text.strip() if name_elements else ""
        specs = computer_info.find_elements(
            By.CSS_SELECTOR, 'div[data-testid="ProductListSpecs"]'
        )
        computer_spec = " / ".join(
            spec.text.strip() for spec in specs if spec.text.strip()
        )

        price_spec = ""
        price_text = ""
        spans = price_info.find_elements(By.CSS_SELECTOR, "li > div span")
        for span in spans:
            text = span.text.strip()
            if not text or "위" in text:
                continue
            if "원" in text:
                break
            if "B" in text:
                price_spec = text
            elif re.search(r"\d", text):
                price_text = text

        return {
            "index": (page_num - 1) * PRODUCTS_PER_PAGE + item_index,
            "computer_name": computer_name,
            "computer_spec": computer_spec,
            "price_spec": price_spec,
            "price": parse_price(price_text),
        }
    except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
        logger.exception("상품 추출 실패: 페이지 %d, 순번 %d", page_num, item_index)
        return None


def wait_for_products(driver, wait):
    """상품 목록이 표시될 때까지 기다리고 현재 WebElement 목록을 반환합니다."""
    return wait.until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, PRODUCT_SELECTOR))
    )


def click_page_with_retry(driver, wait, page_num, old_first_product):
    """페이지 버튼을 매 시도마다 다시 찾아 클릭하고 목록 갱신을 기다립니다."""
    for attempt in range(1, 4):
        try:
            button = wait.until(
                lambda current_driver: next(
                    (
                        item
                        for item in current_driver.find_elements(
                            By.CSS_SELECTOR, PAGER_SELECTOR
                        )
                        if item.text.strip() == str(page_num)
                        and item.is_displayed()
                        and item.is_enabled()
                    ),
                    False,
                )
            )
            old_first_text = old_first_product.text
            button.click()
            wait.until(
                EC.any_of(
                    EC.staleness_of(old_first_product),
                    lambda current_driver: (
                        bool(current_driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR))
                        and current_driver.find_elements(
                            By.CSS_SELECTOR, PRODUCT_SELECTOR
                        )[0].text
                        != old_first_text
                    ),
                )
            )
            wait_for_products(driver, wait)
            logger.info("%d페이지 이동 완료", page_num)
            return True
        except (TimeoutException, StaleElementReferenceException, WebDriverException):
            logger.exception("%d페이지 클릭/대기 실패 (%d/3)", page_num, attempt)
            if attempt < 3:
                time.sleep(1)
    return False


def collect_all_pages(driver, wait):
    """90개 보기로 설정하고 1~10페이지의 상품을 수집합니다."""
    logger.info("다나와 게이밍 PC 페이지 접속")
    driver.get(PAGE_URL)
    wait.until(EC.visibility_of_element_located((By.TAG_NAME, "footer")))

    selects = driver.find_elements(By.TAG_NAME, "select")
    if selects:
        try:
            Select(selects[0]).select_by_value(str(PRODUCTS_PER_PAGE))
            wait.until(
                lambda current_driver: len(
                    current_driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR)
                ) == PRODUCTS_PER_PAGE
            )
            logger.info("페이지당 상품 수를 %d개로 설정했습니다.", PRODUCTS_PER_PAGE)
        except (NoSuchElementException, TimeoutException, StaleElementReferenceException):
            # 옵션/페이지 크기 선택이 없거나 갱신이 늦으면 현재 표시된 목록으로 진행합니다.
            logger.warning("90개 보기 설정을 확인하지 못했습니다. 현재 목록으로 진행합니다.")

    all_rows = []
    for page_num in range(1, PAGE_COUNT + 1):
        products = wait_for_products(driver, wait)
        page_rows = []
        for item_index, product in enumerate(products):
            row = collect_product(product, page_num, item_index)
            if row is not None:
                page_rows.append(row)
        all_rows.extend(page_rows)
        logger.info("%d페이지 수집: %d개", page_num, len(page_rows))

        if page_num < PAGE_COUNT:
            if not products or not click_page_with_retry(
                driver, wait, page_num + 1, products[0]
            ):
                logger.error("%d페이지 이동에 실패해 수집을 중단합니다.", page_num + 1)
                break
    return all_rows


def save_to_postgresql(df):
    """환경 변수에서 접속 정보를 읽어 날짜별 PostgreSQL 테이블에 저장합니다."""
    password = os.getenv("PGPASSWORD")
    if not password:
        password = getpass("PostgreSQL 비밀번호 (또는 PGPASSWORD 환경 변수 사용): ")
    if not password:
        raise ValueError("PostgreSQL 비밀번호가 입력되지 않았습니다.")

    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("PGUSER", "postgres"),
        password=password,
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "postgres"),
    )
    table_name = f"danawa_gaming_pc_{TODAY:%y%m%d}"
    engine = create_engine(db_url)
    try:
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists="replace",  # 같은 날 재실행해도 중복 누적을 방지합니다.
            index=False,
            dtype={
                "index": BigInteger(),
                "computer_name": Text(),
                "computer_spec": Text(),
                "price_spec": Text(),
                "price": Integer(),
            },
        )
        logger.info("PostgreSQL 저장 완료: %s, %d건", table_name, len(df))
    finally:
        engine.dispose()


def main():
    driver = None
    try:
        driver = webdriver.Chrome()
        wait = WebDriverWait(driver, WAIT_SECONDS)
        rows = collect_all_pages(driver, wait)
        df_total = pd.DataFrame(
            rows,
            columns=["index", "computer_name", "computer_spec", "price_spec", "price"],
        )

        logger.info("중복 제거 전 데이터: %d건", len(df_total))
        if not df_total.empty:
            df_total["price"] = pd.to_numeric(df_total["price"], errors="coerce")
            df_total = df_total.dropna(subset=["price"]).copy()
            df_total["price"] = df_total["price"].astype("int64")
            df_total = df_total.drop_duplicates(
                subset=["computer_name", "computer_spec", "price_spec", "price"]
            ).reset_index(drop=True)
        logger.info("가격 누락 제거 및 중복 제거 후: %d건", len(df_total))

        df_total.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        logger.info("CSV 저장 완료: %s", CSV_FILE.resolve())
        save_to_postgresql(df_total)
        logger.info("수집 및 저장이 모두 완료되었습니다.")
        print(df_total.info())
        print(df_total.head())
    except TimeoutException:
        logger.exception("페이지 로딩 제한 시간(%d초)을 초과했습니다.", WAIT_SECONDS)
    except Exception:
        logger.exception("수집 또는 저장 중 오류가 발생했습니다.")
        raise
    finally:
        if driver is not None:
            driver.quit()
            logger.info("브라우저를 종료했습니다.")


if __name__ == "__main__":
    main()