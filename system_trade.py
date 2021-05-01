import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import requests
import time
from urllib.parse import urlencode
import uuid

import jwt

import numpy as np
from slacker import Slacker

MARKET_URL = "https://api.upbit.com/v1/market/all"
MINUTE_URL = "https://api.upbit.com/v1/candles/minutes/"
TICKER_URL = "https://api.upbit.com/v1/ticker"
ACCOUNT_URL = "https://api.upbit.com/v1/accounts"
ORDER_URL = "https://api.upbit.com/v1/orders/"

response = requests.request("GET", MARKET_URL, params={"isDetails":"false"})
codes = json.loads(response.text)
codes = [item for item in codes if 'KRW' in item["market"]]

#argparse로 채우기(ex. 'BTC','XRP')
parser = argparse.ArgumentParser(description='Argparse Tutorial')
# argument는 원하는 만큼 추가한다.
parser.add_argument('--banned', type=str, nargs='*',
                    help='these codes are not traded')
args = parser.parse_args()
codes_manual = args.banned

# 봇 매매 종목은 이 list of dict에서 관리
codes_bot = []
BUY_LIMIT = 4

# TODO
# 체결 주문 확인해서 업데이트 필요
profit = 0

# 손절선, 익절선
LOSS_LIMIT = 2.0
PROFIT_LIMIT = 4.0

if not os.path.exists('logs'):
    os.makedirs('logs')

#auth info
with open('secret','r') as file:
    read = file.read().split('\n')
    slack_token = read[0]
    access_key = read[1]
    secret_key = read[2]

slack = Slacker(slack_token)

def printlog(message, *args):
    """인자로 받은 문자열을 파이썬 셸에 출력한다."""
    print(datetime.now().strftime('[%m/%d %H:%M:%S]'), message, *args)
    filename = datetime.utcnow().strftime('%y%m%d')
    with open ('logs/'+filename,'a') as f:
        #print(datetime.utcnow().strftime('[%m/%d %H:%M:%S]'), message, *args, file=f)
        output = datetime.now().strftime('[%m/%d %H:%M:%S]') + ' '
        output += message+' '
        for arg in args:
            output += str(arg)+' '
        f.write(output + "\n")

def dbgout(message):
    """인자로 받은 문자열을 파이썬 셸과 슬랙으로 동시에 출력한다."""
    printlog(datetime.now().strftime('[%m/%d %H:%M:%S]'), message)
    strbuf = datetime.now().strftime('[%m/%d %H:%M:%S] ') + message
    slack.chat.post_message('#upbit-trading', strbuf)

# 계좌 체크 함수들
def get_balance():
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
    }
    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = f'Bearer {jwt_token}'
    headers = {"Authorization": authorize_token}
    res = requests.get(ACCOUNT_URL, headers=headers)
    return (res.json())

def get_possible_krw():
    """거래에 사용할 금액"""
    possible = get_balance()
    print(possible)
    possible = [float(item['balance']) for item in possible if item['currency']=='KRW'][0]
    return min(2000000.0, possible)

def get_current_krw():
    """거래에 사용할 금액"""
    possible = get_possible_krw()
    assets = get_balance()
    codes_bot = [item for item in assets if item['currency'] not in codes_manual and item['currency'] != 'KRW']
    if len(codes_bot)==BUY_LIMIT:
        return 0.0
    else:
        current = 0.0
        for item in codes_bot:
            current += float(item['balance'])*float(item['avg_buy_price'])
        if current >= possible:
            return 0.0
        else:
            return possible/BUY_LIMIT

    

# 매수 체크 함수들
def get_minutes_candle(code, unit, count=1):
    url = f"{MINUTE_URL}{unit}"
    param_str={"market":code, "count":count}
    response = requests.request("GET", url, params=param_str)
    return json.loads(response.text)

def get_moving_average(candles):
    candles = np.array(candles)
    prices = [item['trade_price'] for item in candles]
    price = sum(prices)/len(prices)
    volumes = [item['candle_acc_trade_volume'] for item in candles]
    volume = sum(volumes)/len(prices)
    return price, volume

def get_new_nominates():
    """주기적으로 24시간 거래대금 높은 애들 받아옴"""
    markets = [item["market"] for item in codes]
    param_str = ",".join(markets)
    response = requests.request("GET", TICKER_URL, params={"markets":param_str})
    nominates = json.loads(response.text)
    nominates = sorted(nominates, key=lambda nom:nom["acc_trade_price_24h"], reverse=True)
    # argument로 알려준 금지 종목은 취급하지 않음
    banned = [f"KRW-{item}" for item in codes_manual]
    nominates = [item for item in nominates if item["market"] not in banned]
    return nominates[:20]

def check_buyable(code):
    """3분봉이 양봉이고, 5분간 이동평균선 > 10분간 이동평균선이면 살만함"""
    res = get_minutes_candle(code, 3)[0]
    if res['trade_price'] < res['opening_price']:
        return False, res['trade_price']
    ma5_candles = get_minutes_candle(code, 1, 5)
    ma5_price, ma5_volume = get_moving_average(ma5_candles)
    ma10_candles = get_minutes_candle(code, 1, 10)
    ma10_price, ma10_volume = get_moving_average(ma10_candles)
    return ma5_price > ma10_price and ma5_volume > 1.2*ma10_volume, res['trade_price']

# 매수 주문
def order_buy(code, current_price, krw):
    global codes_bot
    print('### check what i have before buy')
    already_have = [f"KRW-{item['currency']}" for item in codes_bot]
    print(already_have)
    if len(codes_bot) >= BUY_LIMIT or code in already_have:
        print('already bought or full!')
        return
    if krw == 0:
        print('no possible money')
        return
    query = {
	'market': code,
	'side': 'bid',
	'volume': str(float(krw)/current_price),
	'price': current_price,
	'ord_type': 'limit',
    }
    query_string = urlencode(query).encode()
    m = hashlib.sha512()
    m.update(query_string)
    query_hash = m.hexdigest()
    payload = {
	'access_key': access_key,
	'nonce': str(uuid.uuid4()),
	'query_hash': query_hash,
	'query_hash_alg': 'SHA512',
    }
    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = f'Bearer {jwt_token}'
    headers = {"Authorization": authorize_token}
    res = requests.post(ORDER_URL, params=query, headers=headers)
    printlog(f"buy result : {res.text}")

# 매도 주문
def order_sell(code):
    name = code.split('-')[1]
    assets = get_balance()
    for item in assets:
        if item['currency'] == name:
            amount = item['balance']
    printlog(f"sell {code} of amount {amount}")
    query = {
	'market': code,
	'side': 'ask',
	'volume': amount,
        'ord_type': 'market', #매도는 시장가로 일괄
    }
    query_string = urlencode(query).encode()
    m = hashlib.sha512()
    m.update(query_string)
    query_hash = m.hexdigest()
    payload = {
	'access_key': access_key,
	'nonce': str(uuid.uuid4()),
	'query_hash': query_hash,
	'query_hash_alg': 'SHA512',
    }
    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = f'Bearer {jwt_token}'
    headers = {"Authorization": authorize_token}
    res = requests.post(ORDER_URL, params=query, headers=headers)
    printlog(f"sell result : {res.text}")

# 사놓은 애들 손절or 익절
def check_earning():
    assets = get_balance()
    time.sleep(0.1)
    global codes_bot
    codes_bot = [item for item in assets if item['currency'] not in codes_manual and item['currency'] != 'KRW']
    earning_map = {f"KRW-{item['currency']}":float(item['avg_buy_price']) for item in codes_bot}
    markets = [f"KRW-{item['currency']}" for item in assets if item['currency'] not in codes_manual and item['currency'] != 'KRW']
    param_str = ",".join(markets)
    if param_str=='':
        return {}
    print(f"param_str : {param_str}")
    response = requests.request("GET", TICKER_URL, params={"markets":param_str})
    response = json.loads(response.text)
    for item in response:
        if item['market'] in earning_map:
            earning_map[item['market']] = (item['trade_price'] - earning_map[item['market']])/earning_map[item['market']]
    return earning_map

def trade_by_threshold(earning_map):
    for code, rate in earning_map.items():
        printlog(f"{code} : {rate*100}")
        if rate*100 < -abs(LOSS_LIMIT):
            printlog(f"{code} touch loss limit")
            order_sell(code)
        if rate*100 > abs(PROFIT_LIMIT):
            ma3_candles = get_minutes_candle(code, 1, 3)
            ma3_price, ma3_volume = get_moving_average(ma3_candles)
            ma6_candles = get_minutes_candle(code, 1, 6)
            ma6_price, ma6_volume = get_moving_average(ma6_candles)
            time.sleep(0.1)
            if ma3_price < ma6_price and ma3_volume < ma6_volume:
                order_sell(code)

#main
krw = get_possible_krw()
assets = get_balance()
codes_bot = [item for item in assets if item['currency'] not in codes_manual and item['currency'] != 'KRW']
while(True):
    for item in get_new_nominates():
        time.sleep(1)
        flag, target_price = check_buyable(item['market'])
        if flag:
            order_buy(item['market'],target_price, get_current_krw())
    trade_by_threshold(check_earning())
