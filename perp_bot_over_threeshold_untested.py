from pybit.unified_trading import HTTP
from time import sleep
from decimal import Decimal, ROUND_DOWN
import requests
import socket
import os
import json
from dotenv import load_dotenv

load_dotenv()

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
TESTNET = False  # True means your API keys were generated on testnet.bybit.com
START_PRICE_QTY = 30
SYMBOL = 'ETHUSDT'
TOKEN_START_PRICE = 0.0
TOKEN_PROFIT_PRICE = 0.0
COIN = 'ETH'
HELP_COIN = 'USDT'
CONNECTION_ERRORS = (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                     requests.exceptions.Timeout, socket.timeout)
CONNECTION_ERRORS += (ConnectionResetError,)
# ✅ File to store held tokens
HELD_TOKENS_FILE = "held_tokens.json"
PRICE_HISTORY_FILE = "price_history.json"
TOKEN_PRICES_FILENAME = "token_prices.txt"


def make_order(symbol, side, qty, take_profit=None, stop_loss=None):
    order_params = {
        "category": "linear",      # <-- ова е промената, беше "spot"
        "symbol": symbol,
        "side": side,
        "orderType": "Market",
        "qty": qty,
    }
    if take_profit:
        order_params["takeProfit"] = str(take_profit)
    if stop_loss:
        order_params["stopLoss"] = str(stop_loss)
    
    print(session.place_order(**order_params))


def set_trailing_stop(symbol, stop_loss, trailing_distance, activation_price=None):
    """
    trailing_distance = колку $ назад да затвори (нпр. 20 = затвори ако цената падне $20 од врв)
    stop_loss = фиксен SL (цена)
    activation_price = trailing почнува дури кога цената ќе стигне тука (optional)
    """
    params = {
        "category": "linear",
        "symbol": symbol,
        "trailingStop": str(trailing_distance),
        "stopLoss": str(round(stop_loss, 2)),
        "tpslMode": "Full",
        "positionIdx": 0,
    }
    if activation_price:
        params["activePrice"] = str(round(activation_price, 2))
    
    print(session.set_trading_stop(**params))

def make_order_spot(symbol, side, qty):    
    print(session.place_order(
        category="spot",
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=qty,
        orderFilter="Order",
    ))

def make_tp_order(symbol, side, qty):
    print(session.place_order(
        category="spot",
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=qty,
        orderFilter="Order",
    ))

def get_token_price(symbol):
    response_price_dict = session.get_tickers(
        category="spot",
        symbol=symbol,
    )
    token_price = response_price_dict['result']['list'][0]['ask1Price']
    print('price')
    print(token_price)

    return token_price

def get_token_balance(coin):
    response_dict = session.get_wallet_balance(
        accountType="UNIFIED",
    )
    for c in response_dict['result']['list'][0]['coin']:
        if c['coin'] == coin:
            return float(c['walletBalance'])
    return 0.0

MARGIN_PER_TRADE = 30  # $30 по позиција
LEVERAGE = 20

def calculate_qty(token_price):
    # $30 * 20x = $600 нотионал вредност
    notional = MARGIN_PER_TRADE * LEVERAGE
    qty = notional / token_price
    # Bybit ETHUSDT минимум е 0.01, заокружи на 2 децимали
    qty = float(Decimal(str(qty)).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
    return str(qty)

def get_token_balance_spot(coin):
    response_dict = session.get_coin_balance(
        accountType="UNIFIED",
        coin=coin,
        memberId="554157379"
    )
    token_wallet_balance = float(response_dict['result']['balance']['walletBalance'])

    return token_wallet_balance

# ✅ Save Held Tokens to File (every time we buy/sell)
def save_held_tokens():
    global held_tokens, held_token_prices
    
    data = {
        "held_tokens": list(held_tokens),
        "held_token_prices": held_token_prices
    }
    
    with open(HELD_TOKENS_FILE, "w") as file:
        json.dump(data, file, indent=4)


# ✅ Load Held Tokens from File (at startup)
def load_held_tokens():
    global held_tokens, held_token_prices

    if os.path.exists(HELD_TOKENS_FILE):
        with open(HELD_TOKENS_FILE, "r") as file:
            data = json.load(file)
            held_tokens = set(data.get("held_tokens", []))
            held_token_prices = data.get("held_token_prices", {})
        print(f"🔄 Loaded {len(held_tokens)} held tokens from file.")


def has_open_position(symbol):
    result = session.get_positions(category="linear", symbol=symbol)
    positions = result['result']['list']
    for pos in positions:
        if float(pos['size']) > 0:
            return True
    return False


def find_price_jump(token_price_history, min_x, percentage_threshold=0.03):
    prices = token_price_history[-min_x:]  # Get the last min_x prices
    min_price = float('inf')  # Start with a very high number
    last_price = None  # Store the last price when threshold is crossed
    price_change = 0.0

    for price in prices:
        if price < min_price:
            min_price = price  # Update min_price if a new lower value is found
        
    price_change_temp = (token_price_history[-1] - min_price) / min_price
    print(f"cenata se promenila od minimalista cena za {price_change_temp} procenti")
    if price_change_temp >= percentage_threshold:
        price_change = price_change_temp

    #ako e pod threshold promenata na cenata vrati 0
    if price_change == 0:
        return 0

    return price_change  # ako e nad threshold vrati ja promenata na cenata


# **Load price history from file**
def load_price_history():
    if os.path.exists(PRICE_HISTORY_FILE):
        with open(PRICE_HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}

# **Save price history to file**
def save_price_history(price_history):
    with open(PRICE_HISTORY_FILE, "w") as f:
        json.dump(price_history, f)

def save_prices(start_price, profit_price):
    with open(TOKEN_PRICES_FILENAME, "w") as file:
        file.write(f"{start_price},{profit_price}")


def load_prices():
    if os.path.exists(TOKEN_PRICES_FILENAME):
        with open(TOKEN_PRICES_FILENAME, "r") as file:
            data = file.read().strip()
            if data:
                start_price, profit_price = map(float, data.split(","))
                return start_price, profit_price
    return None, None  # Default values if file doesn't exist



import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import find_peaks

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

import random
import pandas as pd

def detect_spikes_dynamic2(prices, min_spike=30, max_spike=300, recovery_threshold=0.053, max_time_range=240):
    """
    Detects significant price spikes by comparing each price with previous values across random time ranges.

    Parameters:
        prices (list): List of prices.
        min_spike (float): Minimum valid spike size in absolute price movement.
        max_spike (float): Maximum valid spike size.
        recovery_threshold (float): Minimum price increase after a down spike to count as recovery.
        max_time_range (int): Maximum lookback range (in number of data points). Time ranges will be randomly chosen up to this limit.

    Returns:
        list: List of tuples [(index, time_range, 'up'/'down'/'recovery', price change), ...]
    """
    df = pd.DataFrame({'price': prices})
    
    # Generate random time ranges between 1 and max_time_range
    random_time_ranges = list(range(1, max_time_range + 1, 19))

    real_spikes = []
    last_down_index = {t: None for t in random_time_ranges}
    last_down_price = {t: None for t in random_time_ranges}

    for idx in range(1, len(df)):
        for time_range in random_time_ranges:
            if idx - time_range >= 0:
                past_price = df['price'].iloc[idx - time_range]
                current_price = df['price'].iloc[idx]
                change = round(float(current_price - past_price), 4)

                if min_spike <= abs(change) <= max_spike:
                    direction = "up" if change > 0 else "down"
                    real_spikes.append((idx, time_range, direction, round(change, 4)))

    return real_spikes

def detect_spikes_dynamic(prices, min_spike=30, max_spike=300, max_time_range=240):
    """
    prices: листа на цени (најновата последна)
    min_spike, max_spike: во USDT
    max_time_range: колку чекори наназад да гледа (на пр. 240 = 2 часа ако собираш цена на 30 секунди)
    """
    df = pd.DataFrame({'price': prices})
    random_time_ranges = list(range(1, max_time_range + 1, 19))  # интервали 1,20,39,... до max_time_range
    real_spikes = []

    # Почни од индекс 1 за да можеш да споредуваш со претходни цени
    for idx in range(1, len(df)):
        for time_range in random_time_ranges:
            if idx - time_range < 0:
                continue
            past_price = df['price'].iloc[idx - time_range]
            current_price = df['price'].iloc[idx]
            change = round(float(current_price - past_price), 4)
            if min_spike <= abs(change) <= max_spike:
                direction = "up" if change > 0 else "down"
                real_spikes.append((idx, time_range, direction, change))
    return real_spikes

def save_spike_results(results, filename="spike_results.txt"):
    with open(filename, "w") as f:
        for entry in results:
            f.write(f"{entry}\n")


import numpy as np
from collections import defaultdict

def format_spikes_last_only(spike_results):
    last_spikes = {}  # Dictionary to store the last spike per time range

    for idx, time_range, spike_type, change in spike_results:
        change = round(float(change), 4)  # Ensure it's a standard float
        last_spikes[time_range] = (idx, time_range, spike_type, change)  # Store only the last occurrence

    # Convert to a list of tuples
    formatted_spikes = list(last_spikes.values())

    return formatted_spikes

import numpy as np

def calculate_noise(prices, window=120):
    """
    prices: листа на цени (последните N)
    window: колку назад гледаш (120 = 1 час ако собираш на 30 сек)
    
    Враќа: прагот над кој движењето е сигнал
    """
    if len(prices) < window:
        return None
    
    recent = prices[-window:]
    
    # Пресметај ги промените меѓу секој чекор
    changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
    
    # Стандардна девијација = просечен "шум"
    noise_std = np.std(changes)
    
    # ATR = просечна апсолутна промена
    atr = np.mean([abs(c) for c in changes])
    
    return noise_std, atr

def get_signal_threshold(prices, window=120, multiplier=3.0):
    """
    multiplier = колку пати над шумот да бараш
    - 2.0 = повеќе тrejdови, повеќе лажни сигнали
    - 3.0 = помалку тrejdови, попрецизни (препорачано)
    - 4.0 = само најголемите движења
    """
    if len(prices) < window:
        return 30  # default
    
    recent = prices[-window:]
    changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
    
    noise_std = np.std(changes)
    
    # Праг = multiplier * шум
    threshold = noise_std * multiplier
    
    return threshold

def detect_signal(prices, window=120, lookback=240, multiplier=3.0):
    """
    window: период за мерење шум (120 = 1 час)
    lookback: колку назад бараш spike (240 = 2 часа)
    multiplier: чувствителност
    """
    threshold = get_signal_threshold(prices, window, multiplier)
    
    recent = prices[-lookback:]
    current = prices[-1]
    min_price = min(recent)
    max_price = max(recent)
    
    drop = current - max_price   # негативно ако паднала
    rise = current - min_price   # позитивно ако скокнала
    
    print(f"Noise threshold: ${threshold:.2f}")
    print(f"Max drop: ${drop:.2f}, Max rise: ${rise:.2f}")
    
    if abs(drop) > threshold:
        return "down", drop, threshold
    elif rise > threshold:
        return "up", rise, threshold
    
    return "neutral", 0, threshold




session = HTTP(
    api_key=BYBIT_API_KEY,
    api_secret=BYBIT_API_SECRET,
    testnet=TESTNET,
)

# ✅ Global variables
held_tokens = set()
held_token_prices = {}
load_held_tokens()
price_history = load_price_history()
X = 500  # ✅ Check last 10 hours dynamically
min_X = 10  # ✅ Check last 5 minutes dynamically
smart_take_profit = False
can_buy = False
can_sell = False
sell_before = False
buy_before = False
position = "neutral"
low_point = 0
line_smart_buy = False
high_point = 0
line_smart_sell = False

# Example Usage
TOKEN_START_PRICE, TOKEN_PROFIT_PRICE = load_prices()
if TOKEN_START_PRICE is None or TOKEN_PROFIT_PRICE is None:
    TOKEN_START_PRICE = 0.0  # Default values
    TOKEN_PROFIT_PRICE = 0.0
    save_prices(TOKEN_START_PRICE, TOKEN_PROFIT_PRICE)


token_history_price = float(get_token_price(SYMBOL))
sleep(30)

while True:
    try:
        token_price = float(get_token_price(SYMBOL))
        grass = get_token_balance(COIN)
        usdt = get_token_balance(HELP_COIN)
        print('ETH')
        print(grass)
        print('USDT')
        print(usdt)
        # **Price Change Calculation**
        historical_prices = price_history.get(COIN, {}).get("prices", [])
        
        # Append latest token price
        if token_price:
            historical_prices.append(token_price)

        # Keep only last X prices
        price_history[COIN] = {"prices": historical_prices[-X:]}
        save_price_history(price_history)

        # Ensure price change is calculated over 2.5 minutes to 4 hours
        if len(historical_prices) < min_X:
            continue
        
        # Extract price history
        token_price_history = [entry for entry in historical_prices]

        # Ensure we have enough history
        if len(token_price_history) < min_X:
            continue
        short_array = 3
        save_price_history(price_history)
        print(f"🔍 DEBUG: red if can_buy == False and can_sell == False:")
        if can_buy == False and can_sell == False:
            print(f"🔍 DEBUG: vo if can_buy == False and can_sell == False:")
            spike_fluct = 0.0
            # Run detection function
            #spike_results = detect_spikes_dynamic(token_price_history)
            #nested_spikes = format_spikes_last_only(spike_results)  # Format them properly
            # Save results to a text file
            # Наместо фиксен spike >= 30, сега:
            signal, change, threshold = detect_signal(
                historical_prices, 
                window=120,      # 1 час за мерење шум
                lookback=240,    # 2 часа за барање spike
                multiplier=3.0   # 3x над шумот
)
            #save_spike_results(spike_results)

            print("Spikes saved to spike_results.txt")
            #print(spike_results)
            # Check if down exists 
            #ako iame fluktacii od 6.5 do 16 centi
            print(f"🔍 DEBUG: pred if spike_fluct <= 0 and abs(spike_fluct) >= 0.053:")
            if signal == "down" and not has_open_position(SYMBOL):
                qty = calculate_qty(token_price)
                make_order(SYMBOL, 'Sell', qty)
                sleep(2)
                set_trailing_stop(SYMBOL, token_price + threshold*0.3, threshold*0.6, token_price - threshold*0.6)
                can_sell = False
                can_buy = True
                if position == "neutral":
                    position = "down"
                #short = len(token_price_history) - short_array
                price_history[COIN] = {"prices": historical_prices[-3:]}
                save_price_history(price_history)
            elif signal == "up" and not has_open_position(SYMBOL):
                qty = calculate_qty(token_price)
                make_order(SYMBOL, 'Buy', qty)
                sleep(2)
                set_trailing_stop(SYMBOL, token_price - threshold*0.3, threshold*0.6, token_price + threshold*0.6)
                print(f"🔍 DEBUG: vo elif spike_fluct >= 0 and spike_fluct >= 30:")
                TOKEN_PROFIT_PRICE = token_price + 20
                TOKEN_START_PRICE = token_price - 10
                can_buy = False
                can_sell = True
                if position == "neutral":
                    position = "up"
                price_history[COIN] = {"prices": historical_prices[-3:]}
                save_price_history(price_history)

        print(f"🔍 DEBUG: pred kupuvame prodavame")
        if can_sell == False and can_buy == True and position == "down":
            if position != "neutral" and not has_open_position(SYMBOL):
                print("Position closed by trailing stop or SL")
                position = "neutral"
                can_buy = False
                can_sell = False
                sell_before = True
                can_buy = False
                can_sell = False
                line_smart_buy = False
                low_point = 0
                TOKEN_PROFIT_PRICE = 0.0
                TOKEN_START_PRICE = 0.0
                price_history[COIN] = {"prices": historical_prices[-3:]}
                save_price_history(price_history)
            
        elif can_sell == True and can_buy == False and position == 'up':
            if position != "neutral" and not has_open_position(SYMBOL):
                print("Position closed by trailing stop or SL") 
                position = "neutral"
                sell_before = False
                can_buy = False
                can_sell = False
                high_point = 0
                line_smart_sell = False
                TOKEN_PROFIT_PRICE = 0.0
                TOKEN_START_PRICE = 0.0
                price_history[COIN] = {"prices": historical_prices[-3:]}
                save_price_history(price_history)

        print('TOKEN_START_PRICE')
        print(TOKEN_START_PRICE)
        print('TOKEN_PROFIT_PRICE')
        print(TOKEN_PROFIT_PRICE)

        token_history_price = token_price
        sleep(30)
    except CONNECTION_ERRORS as e:
        print(f'Éxception  {e}')
    except Exception as e:
        print(f'Éxception  {e}') 

#print(get_token_balance(COIN))
