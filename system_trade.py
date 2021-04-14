from datetime import datetime, timedelta, timezone
import requests
import json
import time

import numpy as np
from slacker import Slacker

MARKET_URL = "https://api.upbit.com/v1/market/all"
MINUTE_URL = "https://api.upbit.com/v1/candles/minutes/3"
TICKER_URL = "https://api.upbit.com/v1/ticker"

response = requests.request("GET", MARKET_URL, params={"isDetails":"false"})
codes = json.loads(response.text)
codes = [item for item in codes if 'KRW' in item["market"]]

def printlog(message, *args):
    """인자로 받은 문자열을 파이썬 셸에 출력한다."""
    print(datetime.now().strftime('[%m/%d %H:%M:%S]'), message, *args)
    filename = datetime.utcnow().strftime('%y%m%d')
    with open ('logs/'+filename,'a') as f:
        #print(datetime.utcnow().strftime('[%m/%d %H:%M:%S]'), message, *args, file=f)
        output = message
        for arg in args:
            output += str(arg)
        f.write(output + "\n")

def dbgout(message):
    """인자로 받은 문자열을 파이썬 셸과 슬랙으로 동시에 출력한다."""
    printlog(datetime.now().strftime('[%m/%d %H:%M:%S]'), message)
    strbuf = datetime.now().strftime('[%m/%d %H:%M:%S] ') + message
    slack.chat.post_message('#upbit-trading', strbuf)

def get_new_nominates():
    """주기적으로 24시간 거래대금 높은 애들 받아옴"""
    markets = [item["market"] for item in codes]
    param_str = ",".join(markets)
    response = requests.request("GET", TICKER_URL, params={"markets":param_str})
    nominates = json.loads(response.text)
    nominates = sorted(nominates, key=lambda nom:nom["acc_trade_price_24h"], reverse=True)
    return nominates[:20]

# 후보 중에 몇 개 사는 로직 구상
# 사놓은 애들 손절선 익절선 구상

# TEST BELOW
#print(get_new_nominates())
nominates = get_new_nominates()
for item in nominates:
    print(item)
'''
for i in range(3):
    querystring = {"market":codes[i]["market"], "count":1}
    print(requests.request("GET", minute_url, params=querystring).text)
    querystring = {"markets":codes[i]["market"]}
    ticker = requests.request("GET", TICKER_URL, params=querystring)
    print(ticker.text)
'''
