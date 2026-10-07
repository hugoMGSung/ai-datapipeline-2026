import logging
from datetime import datetime

logfileName = f'logs_{datetime.now().strftime("%y%m%d_%H%M%S")}.log'

logging.basicConfig(
    filename=logfileName,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
    force=True
)

logging.info("로그 시작")

# 여기에 스크래핑과 PostgreSQL 저장 코드

logging.warning("워닝!!!")

logging.info("로그 완료")