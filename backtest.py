"""
ETH Perpetual Bot Backtester
=============================
Тестира различни комбинации на:
- Интервали: 1min, 5min, 15min
- Spike threshold: фиксен (15,20,30,40,50) и динамички (2x,3x,4x шум)
- Trailing stop: 10, 20
- Stop loss: 8, 10, 15
- Activation: 15, 20

Користење: pip install requests numpy pandas
           python backtest_eth_bot.py

Резултатите се зачувуваат во backtest_results.json
"""

import requests, time, json, numpy as np
from datetime import datetime, timedelta, timezone

SYMBOL = "ETHUSDT"
MARGIN = 40
LEV = 20

# ============================================================
# FETCH DATA
# ============================================================
def fetch_all(interval, days):
    """Fetch kline data from Bybit"""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    all_k = []
    cur = start_ms
    
    while cur < end_ms:
        try:
            r = requests.get("https://api.bybit.com/v5/market/kline",
                params={"category": "linear", "symbol": SYMBOL, "interval": str(interval),
                        "start": cur, "limit": 1000}, timeout=10)
            d = r.json()
            if d['retCode'] != 0 or not d['result']['list']:
                break
            kl = d['result']['list']
            all_k.extend(kl)
            cur = max(int(k[0]) for k in kl) + interval * 60000
            time.sleep(0.12)
        except Exception as e:
            print(f"  Fetch error: {e}")
            time.sleep(1)
            continue
    
    prices = sorted(set((int(k[0]), float(k[4])) for k in all_k))
    result = [p for _, p in prices]
    return result

# ============================================================
# SPIKE & NOISE DETECTION
# ============================================================
def detect(prices, thresh, max_tr):
    """Detect spike in price buffer"""
    sf = 0.0
    step = max(1, max_tr // 12)
    trs = list(range(1, min(max_tr + 1, len(prices)), step))
    for tr in trs:
        if len(prices) <= tr:
            continue
        c = prices[-1] - prices[-1 - tr]
        if thresh <= abs(c) <= 300:
            sf = c
    return sf

def noise(prices, w=60, m=3.0):
    """Calculate noise threshold via standard deviation"""
    if len(prices) < w:
        return 30
    r = prices[-w:]
    ch = [r[i] - r[i - 1] for i in range(1, len(r))]
    return max(np.std(ch) * m, 5) if ch else 30

# ============================================================
# BACKTEST ENGINE
# ============================================================
def bt(prices, sp, trail, sl, act, dyn=False, nm=3.0, mtr=48):
    """
    Run backtest on price list
    sp = spike threshold (ignored if dyn=True)
    trail = trailing stop distance
    sl = stop loss distance
    act = activation distance for trailing
    dyn = use dynamic noise threshold
    nm = noise multiplier
    mtr = max time range for spike detection
    """
    trades = []
    pos = None  # None / "long" / "short"
    ent = 0     # entry price
    slp = 0     # stop loss price
    tra = False # trailing active
    trb = 0     # trailing best price
    trs = 0     # trailing stop price
    acp = 0     # activation price
    buf = []    # price buffer
    
    for i, p in enumerate(prices):
        buf.append(p)
        if len(buf) > 300:
            buf = buf[-300:]
        
        # === CHECK EXITS ===
        if pos == "long":
            if p <= slp:
                pnl = (p - ent) * MARGIN * LEV / ent
                trades.append({"t": "L", "pnl": round(pnl, 2), "r": "SL", "e": ent, "x": p, "i": i})
                pos = None
                continue
            if not tra and p >= acp:
                tra = True; trb = p; trs = p - trail
            if tra:
                if p > trb:
                    trb = p; trs = trb - trail
                if p <= trs:
                    pnl = (p - ent) * MARGIN * LEV / ent
                    trades.append({"t": "L", "pnl": round(pnl, 2), "r": "TR", "e": ent, "x": p, "i": i})
                    pos = None
                    continue
                    
        elif pos == "short":
            if p >= slp:
                pnl = (ent - p) * MARGIN * LEV / ent
                trades.append({"t": "S", "pnl": round(pnl, 2), "r": "SL", "e": ent, "x": p, "i": i})
                pos = None
                continue
            if not tra and p <= acp:
                tra = True; trb = p; trs = p + trail
            if tra:
                if p < trb:
                    trb = p; trs = trb + trail
                if p >= trs:
                    pnl = (ent - p) * MARGIN * LEV / ent
                    trades.append({"t": "S", "pnl": round(pnl, 2), "r": "TR", "e": ent, "x": p, "i": i})
                    pos = None
                    continue
        
        # === CHECK ENTRIES ===
        if pos is None and len(buf) >= 10:
            th = noise(buf, 60, nm) if dyn else sp
            sf = detect(buf, th, min(mtr, len(buf)))
            
            if sf < 0 and abs(sf) >= th:
                pos = "short"; ent = p; slp = p + sl; acp = p - act
                tra = False; buf = buf[-3:]
            elif sf > 0 and sf >= th:
                pos = "long"; ent = p; slp = p - sl; acp = p + act
                tra = False; buf = buf[-3:]
    
    # Close open position at end
    if pos:
        p = prices[-1]
        pnl = ((p - ent) if pos == "long" else (ent - p)) * MARGIN * LEV / ent
        trades.append({"t": pos[0].upper(), "pnl": round(pnl, 2), "r": "OP", "e": ent, "x": p, "i": len(prices)-1})
    
    return trades

# ============================================================
# PER-DAY ANALYSIS
# ============================================================
def analyze_per_day(prices_with_ts, sp, trail, sl, act, dyn, nm, mtr):
    """Run backtest per day and show daily breakdown"""
    # Group prices by day
    days = {}
    for ts, price in prices_with_ts:
        day = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if day not in days:
            days[day] = []
        days[day].append(price)
    
    daily_results = []
    for day, prices in sorted(days.items()):
        trades = bt(prices, sp, trail, sl, act, dyn, nm, mtr)
        pnl = sum(t['pnl'] for t in trades)
        daily_results.append({"day": day, "trades": len(trades), "pnl": round(pnl, 2), "details": trades})
    
    return daily_results

# ============================================================
# MAIN
# ============================================================
def run():
    print("=" * 80)
    print("  ETH PERPETUAL BOT BACKTESTER")
    print(f"  Margin: ${MARGIN} | Leverage: {LEV}x | Position size: ${MARGIN*LEV}")
    print("=" * 80)
    
    # Fetch data
    print("\n📥 Fetching 5-min candles (7 days)...")
    p5 = fetch_all(5, 7)
    print(f"   Got {len(p5)} candles")
    
    print("📥 Fetching 15-min candles (7 days)...")
    p15 = fetch_all(15, 7)
    print(f"   Got {len(p15)} candles")
    
    print("📥 Fetching 1-min candles (3 days)...")
    p1 = fetch_all(1, 3)
    print(f"   Got {len(p1)} candles")
    
    data = {"1min": p1, "5min": p5, "15min": p15}
    
    # Build configs
    cfgs = []
    
    # Fixed threshold
    for iv in ["1min", "5min", "15min"]:
        for sp in [15, 20, 30, 40, 50]:
            for tr in [10, 20]:
                for s in [8, 10, 15]:
                    cfgs.append({"iv": iv, "sp": sp, "tr": tr, "sl": s, "act": 20, "d": False})
    
    # Dynamic threshold
    for iv in ["1min", "5min", "15min"]:
        for nm in [2.0, 3.0, 4.0]:
            for tr in [10, 20]:
                for s in [8, 10, 15]:
                    cfgs.append({"iv": iv, "sp": 0, "tr": tr, "sl": s, "act": 20, "d": True, "nm": nm})
    
    print(f"\n🧪 Testing {len(cfgs)} configurations...\n")
    
    res = []
    for i, c in enumerate(cfgs):
        if (i + 1) % 50 == 0:
            print(f"   Progress: {i+1}/{len(cfgs)}")
        
        pr = data[c["iv"]]
        if len(pr) < 20:
            continue
        mtr = {"1min": 120, "5min": 48, "15min": 16}[c["iv"]]
        
        tds = bt(pr, c["sp"], c["tr"], c["sl"], c["act"], c["d"], c.get("nm", 3), mtr)
        if not tds:
            continue
        
        tot = sum(t['pnl'] for t in tds)
        w = len([t for t in tds if t['pnl'] > 0])
        lb = f"{c['iv']}|{'DYN' + str(c.get('nm', '')) if c['d'] else 'FIX' + str(c['sp'])}|trail{c['tr']}|sl{c['sl']}"
        
        res.append({
            "label": lb, "n": len(tds), "w": w,
            "wr": round(w / len(tds) * 100, 1),
            "pnl": round(tot, 2),
            "avg": round(tot / len(tds), 2),
            "mxw": round(max(t['pnl'] for t in tds), 2),
            "mxl": round(min(t['pnl'] for t in tds), 2),
            "sls": len([t for t in tds if t['r'] == 'SL']),
            "trs": len([t for t in tds if t['r'] == 'TR']),
            "cfg": c,
            "td": tds
        })
    
    res.sort(key=lambda x: x['pnl'], reverse=True)
    
    # ============================================================
    # RESULTS
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"  TOP 20 MOST PROFITABLE CONFIGS (last 7 days)")
    print(f"  Budget: ${MARGIN} margin × {LEV}x leverage = ${MARGIN*LEV} position")
    print(f"{'=' * 100}")
    print(f"{'Config':<40} {'#Tr':>4} {'Win':>4} {'WR%':>6} {'PnL$':>9} {'Avg$':>7} {'BestW':>7} {'WorstL':>7} {'SL':>3} {'TR':>3}")
    print("-" * 100)
    
    for r in res[:20]:
        print(f"{r['label']:<40} {r['n']:>4} {r['w']:>4} {r['wr']:>5.1f}% "
              f"{r['pnl']:>9.2f} {r['avg']:>7.2f} {r['mxw']:>7.2f} {r['mxl']:>7.2f} "
              f"{r['sls']:>3} {r['trs']:>3}")
    
    # Best config trade details
    if res:
        b = res[0]
        print(f"\n{'=' * 80}")
        print(f"  BEST CONFIG: {b['label']}")
        print(f"  Total PnL: ${b['pnl']} | Trades: {b['n']} | Win rate: {b['wr']}%")
        print(f"{'=' * 80}")
        for t in b['td']:
            emoji = "🟢" if t['pnl'] > 0 else "🔴"
            print(f"  {emoji} {t['t']} Entry:${t['e']:.2f} → Exit:${t['x']:.2f} = ${t['pnl']:>+8.2f} [{t['r']}]")
    
    # Worst configs
    print(f"\n{'=' * 80}")
    print("  WORST 5 CONFIGS (avoid these!)")
    print(f"{'=' * 80}")
    for r in res[-5:]:
        print(f"  ❌ {r['label']:<40} PnL: ${r['pnl']:>9.2f} ({r['n']} trades, {r['wr']}% WR)")
    
    # Win rate leaders
    print(f"\n{'=' * 80}")
    print("  TOP 10 BY WIN RATE (min 3 trades)")
    print(f"{'=' * 80}")
    wr = [r for r in res if r['n'] >= 3]
    wr.sort(key=lambda x: x['wr'], reverse=True)
    for r in wr[:10]:
        print(f"  {r['label']:<40} WR: {r['wr']}% | {r['n']} trades | PnL: ${r['pnl']}")
    
    # Summary stats
    profitable = len([r for r in res if r['pnl'] > 0])
    print(f"\n{'=' * 80}")
    print(f"  SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Total configs tested: {len(cfgs)}")
    print(f"  Configs with trades: {len(res)}")
    print(f"  Profitable configs: {profitable} ({round(profitable/max(len(res),1)*100,1)}%)")
    if res:
        print(f"  Best PnL: ${res[0]['pnl']} ({res[0]['label']})")
        print(f"  Worst PnL: ${res[-1]['pnl']} ({res[-1]['label']})")
    
    # Save results
    save_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settings": {"margin": MARGIN, "leverage": LEV, "symbol": SYMBOL},
        "results": [{k: v for k, v in r.items() if k not in ('td', 'cfg')} for r in res]
    }
    
    with open("backtest_results.json", "w") as f:
        json.dump(save_data, f, indent=2)
    
    print(f"\n💾 Full results saved to backtest_results.json")
    
    # === RECOMMENDATION ===
    if res and res[0]['pnl'] > 0:
        b = res[0]
        c = b['cfg']
        print(f"\n{'=' * 80}")
        print(f"  ✅ RECOMMENDATION FOR TODAY:")
        print(f"{'=' * 80}")
        print(f"  Interval: check every {c['iv'].replace('min','')} minutes")
        if c['d']:
            print(f"  Threshold: DYNAMIC (noise × {c.get('nm', 3.0)})")
        else:
            print(f"  Threshold: FIXED ${c['sp']}")
        print(f"  Trailing stop: ${c['tr']}")
        print(f"  Stop loss: ${c['sl']}")
        print(f"  Activation: ${c['act']}")
        print(f"\n  Expected: ~{b['n']//7} trades/day, ~${b['pnl']/7:.2f}/day")

if __name__ == "__main__":
    run()
