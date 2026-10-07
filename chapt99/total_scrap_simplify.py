"""다나와 게이밍 PC 수집 및 CSV/PostgreSQL 저장 스크립트.
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


def main():
    # 파일과 로그 저장 위치
    work_dir = Path.cwd()
    data_dir = (work_dir.parent if work_dir.name.lower() == "chapt04" else work_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    csv_file = data_dir / f"danawa_게이밍PC_{now:%Y%m%d}.csv"
    log_file = data_dir / "scraping.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("danawa_scraper")

    driver = None
    engine = None
    danawa_prices = []

    try:
        # 브라우저를 열고 다나와 게이밍 PC 목록으로 이동
        driver = webdriver.Chrome()
        wait = WebDriverWait(driver, 10)
        driver.get("https://prod.danawa.com/list/?cate=11255834&15main_11_02")
        wait.until(EC.visibility_of_element_located((By.TAG_NAME, "footer")))
        logger.info("다나와 페이지 로딩 완료")

        # 페이지당 상품 수를 90개로 변경
        selects = driver.find_elements(By.TAG_NAME, "select")
        if selects:
            try:
                Select(selects[0]).select_by_value("90")
                wait.until(
                    lambda current_driver: len(
                        current_driver.find_elements(
                            By.CSS_SELECTOR, 'div[data-testid="ProductListItem"]'
                        )
                    ) == 90
                )
                logger.info("페이지당 상품 수를 90개로 설정")
            except (NoSuchElementException, TimeoutException, StaleElementReferenceException):
                logger.warning("90개 보기 설정을 확인하지 못했습니다. 현재 목록으로 진행합니다.")

        # 1~10페이지 수집
        for page_num in range(1, 11):
            products = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, 'div[data-testid="ProductListItem"]')
                )
            )
            logger.info("%d페이지 상품 %d개 확인", page_num, len(products))

            for index, product in enumerate(products):
                try:
                    items = product.find_elements(
                        By.CSS_SELECTOR, ".dnw-product-list-item > div"
                    )
                    if len(items) < 3:
                        logger.warning("상품 정보 영역 누락: %d페이지 %d번", page_num, index)
                        continue

                    computer_info = items[1]
                    price_info = items[2]

                    name_elements = computer_info.find_elements(By.CSS_SELECTOR, "div a")
                    computer_name = name_elements[0].text.strip() if name_elements else ""
                    specs = computer_info.find_elements(
                        By.CSS_SELECTOR, 'div[data-testid="ProductListSpecs"]'
                    )
                    computer_spec = " / ".join(
                        spec.text.strip() for spec in specs if spec.text.strip()
                    )

                    # 첫 가격을 찾고, 순위와 가격 비교 옵션은 건너뜀
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

                    digits = re.sub(r"[^0-9]", "", price_text)
                    price = int(digits) if digits else None

                    danawa_prices.append(
                        {
                            "index": (page_num - 1) * 90 + index,
                            "computer_name": computer_name,
                            "computer_spec": computer_spec,
                            "price_spec": price_spec,
                            "price": price,
                        }
                    )
                except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
                    logger.exception("상품 추출 실패: %d페이지 %d번", page_num, index)

            # 다음 페이지 버튼을 매번 새로 찾아 stale element 오류를 예방
            if page_num < 10:
                moved = False
                for attempt in range(1, 4):
                    try:
                        old_first_product = products[0]
                        old_first_text = old_first_product.text
                        page_buttons = driver.find_elements(
                            By.CSS_SELECTOR, "nav > nav div button"
                        )
                        next_button = next(
                            (button for button in page_buttons
                             if button.text.strip() == str(page_num + 1)
                             and button.is_displayed()
                             and button.is_enabled()),
                            None,
                        )
                        if next_button is None:
                            raise NoSuchElementException(
                                f"{page_num + 1}페이지 버튼을 찾지 못했습니다."
                            )

                        next_button.click()
                        wait.until(
                            EC.any_of(
                                EC.staleness_of(old_first_product),
                                lambda current_driver: (
                                    bool(current_driver.find_elements(
                                        By.CSS_SELECTOR, 'div[data-testid="ProductListItem"]'
                                    ))
                                    and current_driver.find_elements(
                                        By.CSS_SELECTOR, 'div[data-testid="ProductListItem"]'
                                    )[0].text != old_first_text
                                ),
                            )
                        )
                        moved = True
                        logger.info("%d페이지 이동 완료", page_num + 1)
                        break
                    except (NoSuchElementException, StaleElementReferenceException,
                            TimeoutException, WebDriverException):
                        logger.exception(
                            "%d페이지 이동 실패 (%d/3)", page_num + 1, attempt
                        )
                        if attempt < 3:
                            time.sleep(1)

                if not moved:
                    logger.error("페이지 이동을 중단합니다.")
                    break

        # DataFrame으로 바꾸고 가격이 없거나 중복된 데이터 정리
        df_total = pd.DataFrame(
            danawa_prices,
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
        logger.info("가격 누락/중복 제거 후 데이터: %d건", len(df_total))

        # CSV 저장
        df_total.to_csv(csv_file, index=False, encoding="utf-8-sig")
        logger.info("CSV 저장 완료: %s", csv_file.resolve())

        # PostgreSQL 접속 정보: 환경 변수를 우선 사용하고 비밀번호만 없으면 입력받음
        db_password = os.getenv("PGPASSWORD")
        if not db_password:
            db_password = getpass("PostgreSQL 비밀번호 (또는 PGPASSWORD 환경 변수 사용): ")
        if not db_password:
            raise ValueError("PostgreSQL 비밀번호가 입력되지 않았습니다.")

        db_url = URL.create(
            "postgresql+psycopg",
            username=os.getenv("PGUSER", "postgres"),
            password=db_password,
            host=os.getenv("PGHOST", "127.0.0.1"),
            port=int(os.getenv("PGPORT", "5432")),
            database=os.getenv("PGDATABASE", "postgres"),
        )
        engine = create_engine(db_url)
        table_name = f"danawa_gaming_pc_{now:%y%m%d}"

        df_total.to_sql(
            name=table_name,
            con=engine,
            if_exists="replace",
            index=False,
            dtype={
                "index": BigInteger(),
                "computer_name": Text(),
                "computer_spec": Text(),
                "price_spec": Text(),
                "price": Integer(),
            },
        )
        logger.info("PostgreSQL 저장 완료: %s (%d건)", table_name, len(df_total))

        # 저장 결과 요약 출력
        print(f"수집 및 저장 완료: {len(df_total)}건")
        print(f"CSV 파일: {csv_file.resolve()}")
        print(f"PostgreSQL 테이블: {table_name}")
        print(df_total.head())

    except TimeoutException:
        logger.exception("페이지 로딩이 10초 안에 끝나지 않았습니다.")
    except Exception:
        logger.exception("수집 또는 저장 중 오류가 발생했습니다.")
        raise
    finally:
        if engine is not None:
            engine.dispose()
        if driver is not None:
            driver.quit()
            logger.info("브라우저 종료")


if __name__ == "__main__":
    main()
