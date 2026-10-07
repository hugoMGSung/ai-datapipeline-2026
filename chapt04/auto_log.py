import logging
from datetime import datetime 

# 로그파일명
logfileName = f'./testlog_{datetime.now().strftime("%y%m%d%H%M%S")}.log'

logging.basicConfig(
    filename=logfileName,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding='utf-8'
)

logging.info('[스케줄]로그 시작')

# ... 여러작업 수행
logging.warning('경고!!!')

logging.info('[스케줄]로그 완료!')