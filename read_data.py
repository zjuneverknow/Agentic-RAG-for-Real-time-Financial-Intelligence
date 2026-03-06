import os
import torch
from typing import List
from dotenv import load_dotenv

import finnhub
import pandas as pd
load_dotenv()

FINN_HUB_API = os.getenv("FINN_HUB_API")
# 初始化客户端
finnhub_client = finnhub.Client(api_key=FINN_HUB_API)

# 获取近三天的苹果公司(AAPL)新闻
news = finnhub_client.company_news('AAPL', _from="2026-03-01", to="2026-03-04")

# 打印第一条看看长什么样
print(news[0])