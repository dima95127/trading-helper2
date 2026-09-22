import os
import threading
import queue
import time
import random
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Rectangle
import yfinance as yf
import ccxt
import pandas as pd
import ta
import requests

PAIRS = {
    'e': {'yf': 'EURUSD=X', 'ccxt': 'EUR/USD', 'investing': 'EUR/USD',
          'coingecko': None, 'glassnode': None,
          'forex_base': 'EUR', 'forex_target': 'USD'},
    'g': {'yf': 'GBPUSD=X', 'ccxt': 'GBP/USD', 'investing': 'GBP/USD',
          'coingecko': None, 'glassnode': None,
          'forex_base': 'GBP', 'forex_target': 'USD'},
    'u': {'yf': 'USDJPY=X', 'ccxt': 'USD/JPY', 'investing': 'USD/JPY',
          'coingecko': None, 'glassnode': None,
          'forex_base': 'USD', 'forex_target': 'JPY'},
    'b': {'yf': 'BTC-USD', 'ccxt': 'BTC/USDT', 'investing': 'BTC/USD',
          'coingecko': 'bitcoin', 'glassnode': 'BTC',
          'forex_base': None, 'forex_target': None},
}
DEFAULT_KEY = 'e'
GLASSNODE_API_KEY = ""

class MartingaleSimulator:
    def __init__(self, initial_bet=50, multiplier=2.0, max_steps=10):
        self.initial_bet = initial_bet
        self.multiplier = multiplier
        self.max_steps = max_steps
        self.reset()
    def reset(self):
        self.current_bet = self.initial_bet
        self.loss_streak = 0
        self.total_risked = 0
        self.balance = 1000
    def simulate_trade(self, signal):
        if signal == "HOLD":
            return "NO_TRADE"
        win = random.random() < 0.7
        pnl = self.current_bet if win else -self.current_bet
        self.balance += pnl
        if win:
            self.win_reset()
            return "WIN"
        else:
            next_bet = self.next_bet_after_loss()
            if next_bet is None:
                return "BUST"
            return "LOSS"
    def next_bet_after_loss(self):
        self.loss_streak += 1
        if self.loss_streak > self.max_steps:
            return None
        self.current_bet *= self.multiplier
        self.total_risked += self.current_bet
        return self.current_bet
    def win_reset(self):
        last_bet = self.current_bet
        self.total_risked += last_bet
        self.loss_streak = 0
        self.current_bet = self.initial_bet
        return last_bet
    def get_status(self):
        potential_future_risk = 0
        current = self.current_bet * self.multiplier
        steps_left = self.max_steps - self.loss_streak
        for _ in range(steps_left):
            potential_future_risk += current
            current *= self.multiplier
        return {
            'current_bet': self.current_bet,
            'loss_streak': self.loss_streak,
            'total_risked': self.total_risked,
            'max_possible_loss': self.total_risked + potential_future_risk,
            'balance': self.balance,
        }

def get_data_yfinance(ticker, minutes=50):
    try:
        df = yf.download(ticker, period="1d", interval="1m")
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.tail(minutes) if not df.empty else None
    except Exception as e:
        print(f"[YF] Error: {e}")
        return None

def get_data_ccxt(ticker, minutes=50, timeframe="1m"):
    try:
        exchange = ccxt.okx({"enableRateLimit": True, "timeout": 8000})
        ohlcv = exchange.fetch_ohlcv(ticker, timeframe=timeframe, limit=minutes)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("time", inplace=True)
        return df
    except Exception as e:
        print(f"[CCXT] Error: {e}")
        return None

def get_data_investing_simulated(pair_name, interval_minutes, minutes_count=50):
    base_price = 1.10
    if "JPY" in pair_name:
        base_price = 150.0
    elif "GBP" in pair_name:
        base_price = 1.27
    elif "BTC" in pair_name:
        base_price = 65000.0
    freq_str = f"{interval_minutes}min"
    dates = pd.date_range(end=pd.Timestamp.now(), periods=minutes_count, freq=freq_str)
    noise = [random.uniform(-0.0002 * interval_minutes, 0.0002 * interval_minutes) for _ in range(minutes_count)]
    trend = [i * 0.00005 * interval_minutes for i in range(minutes_count)]
    prices = [base_price + n + t for n, t in zip(noise, trend)]
    df = pd.DataFrame({
        'open': prices,
        'high': [p + random.uniform(0, 0.0001 * interval_minutes) for p in prices],
        'low':  [p - random.uniform(0, 0.0001 * interval_minutes) for p in prices],
        'close': prices,
        'volume': [random.randint(100, 1000) for _ in range(minutes_count)]
    }, index=dates)
    return df

FOREX_API_SOURCES = [
    ("frankfurter", "https://api.frankfurter.app", "frankfurter"),
    ("fawazahmed0", "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies", "fawazahmed0"),
    ("open_er_api", "https://open.er-api.com/v6", "open_er_api"),
]

def _fetch_forex_rate(base, target):
    for src_name, base_url, fmt in FOREX_API_SOURCES:
        try:
            if fmt == "frankfurter":
                url = f"{base_url}/latest?from={base}&to={target}"
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    rate = data.get("rates", {}).get(target)
                    if rate and rate > 0:
                        return rate, "Frankfurter (ECB)"
            elif fmt == "fawazahmed0":
                url = f"{base_url}/{base.lower()}.json"
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    rates = data.get(base.lower(), {})
                    rate = rates.get(target.lower())
                    if rate and rate > 0:
                        return rate, "FawazAhmed0 (CDN)"
            elif fmt == "open_er_api":
                url = f"{base_url}/pair/{base}/{target}"
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("result") == "success":
                        rate = data.get("conversion_rate")
                        if rate and rate > 0:
                            return rate, "ExchangeRate (open)"
        except Exception as e:
            print(f"[Forex API/{src_name}] Error: {e}")
            continue
    return None, None

def get_data_forex_api(base, target, minutes=50):
    try:
        real_rate, source = _fetch_forex_rate(base, target)
        if real_rate is None:
            return None, None
        dates = pd.date_range(end=pd.Timestamp.now(), periods=minutes, freq="1min")
        noise_scale = abs(real_rate) * 0.0005
        prices = [real_rate + random.uniform(-noise_scale, noise_scale) for _ in range(minutes)]
        trend = [i * noise_scale * 0.1 for i in range(minutes)]
        prices = [p + t for p, t in zip(prices, trend)]
        df = pd.DataFrame({
            'open': prices,
            'high': [p + random.uniform(0, noise_scale * 0.5) for p in prices],
            'low':  [p - random.uniform(0, noise_scale * 0.5) for p in prices],
            'close': prices,
            'volume': [random.randint(100, 1000) for _ in range(minutes)]
        }, index=dates)
        return df, source
    except Exception as e:
        print(f"[Forex API] Error: {e}")
        return None, None

def get_signal_forex_api(base, target):
    try:
        rate_fwd, _ = _fetch_forex_rate(base, target)
        if rate_fwd is None:
            return None
        rate_rev, _ = _fetch_forex_rate(target, base)
        if rate_rev is None:
            return "HOLD"
        product = rate_fwd * rate_rev
        if product > 1.002:
            return "BUY_SIGNAL"
        elif product < 0.998:
            return "SELL_SIGNAL"
        return "HOLD"
    except Exception as e:
        print(f"[Forex API Signal] Error: {e}")
        return None

def get_signal_coingecko(coin_id):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if coin_id not in data:
            return None
        change_24h = data[coin_id].get("usd_24h_change", 0)
        if change_24h > 2.0:
            return "BUY_SIGNAL"
        elif change_24h < -2.0:
            return "SELL_SIGNAL"
        return "HOLD"
    except Exception as e:
        print(f"[CoinGecko Signal] Error: {e}")
        return None

def get_signal_glassnode(asset="BTC"):
    if not GLASSNODE_API_KEY:
        return None
    try:
        url = f"https://api.glassnode.com/v1/metrics/indicators/sopr"
        params = {"a": asset, "api_key": GLASSNODE_API_KEY}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        latest_sopr = data[-1].get("v", 1.0)
        if latest_sopr > 1.05:
            return "SELL_SIGNAL"
        elif latest_sopr < 0.95:
            return "BUY_SIGNAL"
        return "HOLD"
    except Exception as e:
        print(f"[Glassnode] Error: {e}")
        return None

def get_signal_samurai_algo(df):
    try:
        if df is None or df.empty:
            return None
        col = "Close" if "Close" in df.columns else "close"
        close = df[col].squeeze()
        if len(close) < 26:
            return None
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        momentum = close.iloc[-1] - close.iloc[-5]
        score = 0
        if rsi < 30:
            score += 2
        elif rsi > 70:
            score -= 2
        elif rsi < 45:
            score += 1
        elif rsi > 55:
            score -= 1
        if momentum > 0:
            score += 1
        else:
            score -= 1
        if score >= 2:
            return "BUY_SIGNAL"
        elif score <= -2:
            return "SELL_SIGNAL"
        return "HOLD"
    except Exception as e:
        print(f"[Samurai Algo] Error: {e}")
        return None

def get_signal_trademaster_pro(df):
    try:
        if df is None or df.empty:
            return None
        col = "Close" if "Close" in df.columns else "close"
        close = df[col].squeeze()
        if len(close) < 20:
            return None
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        last_close = close.iloc[-1]
        if last_close < bb_lower and rsi < 35:
            return "BUY_SIGNAL"
        elif last_close > bb_upper and rsi > 65:
            return "SELL_SIGNAL"
        return "HOLD"
    except Exception as e:
        print(f"[TradeMaster Pro] Error: {e}")
        return None

def compute_indicators(df):
    if df is None or df.empty:
        return None
    df = df.copy()
    col = "Close" if "Close" in df.columns else "close"
    if col not in df.columns:
        return None
    close_series = df[col].squeeze()
    try:
        df["ma_20"] = ta.trend.sma_indicator(close_series, window=20)
        df["rsi_14"] = ta.momentum.rsi(close_series, window=14)
    except Exception as e:
        print(f"[Indicators] Error: {e}")
        return None
    return df

def generate_signal(row, col_close="close"):
    ma_col = "ma_20" if "ma_20" in row else None
    rsi_col = "rsi_14" if "rsi_14" in row else None
    if ma_col is None or rsi_col is None:
        return "NO_SIGNAL"
    if pd.isna(row[ma_col]) or pd.isna(row[rsi_col]):
        return "HOLD"
    close = row[col_close]
    ma = row[ma_col]
    rsi = row[rsi_col]
    if close > ma and rsi < 70:
        return "BUY_SIGNAL"
    elif close < ma and rsi > 30:
        return "SELL_SIGNAL"
    else:
        return "HOLD"

def generate_tradingview_like_signal(df):
    if len(df) < 2:
        return "HOLD"
    last_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]
    if last_close > prev_close:
        return "BUY_SIGNAL"
    elif last_close < prev_close:
        return "SELL_SIGNAL"
    return "HOLD"


class SignalRow(BoxLayout):
    def __init__(self, source, signal, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = 40
        sig_text = signal.replace("_SIGNAL", "")
        color = (0.4, 0.4, 0.4, 1)
        if signal == "BUY_SIGNAL":
            color = (0, 0.6, 0, 1)
        elif signal == "SELL_SIGNAL":
            color = (0.8, 0, 0, 1)
        lbl_src = Label(text=source, size_hint_x=0.65, color=(1,1,1,1), font_size=14)
        lbl_sig = Label(text=sig_text, size_hint_x=0.35, color=color, bold=True, font_size=14)
        self.add_widget(lbl_src)
        self.add_widget(lbl_sig)


class TradingApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.is_running = False
        self.update_queue = queue.Queue()
        self.martingale = MartingaleSimulator(initial_bet=50, multiplier=2.0, max_steps=8)

        # Top panel
        top = BoxLayout(orientation='horizontal', size_hint_y=None, height=60, padding=5, spacing=5)

        self.pair_spinner = Spinner(
            text='e (EUR/USD)',
            values=['e (EUR/USD)', 'g (GBP/USD)', 'u (USD/JPY)', 'b (BTC/USD)'],
            size_hint_x=0.3
        )
        self.tf_spinner = Spinner(
            text='5m',
            values=['1m', '2m', '3m', '4m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'],
            size_hint_x=0.2
        )
        self.run_btn = Button(text='Start Analysis', size_hint_x=0.3)
        self.run_btn.bind(on_press=self.toggle_analysis)

        self.status_label = Label(text='Status: stopped', size_hint_x=0.2, font_size=13)

        top.add_widget(self.pair_spinner)
        top.add_widget(self.tf_spinner)
        top.add_widget(self.run_btn)
        top.add_widget(self.status_label)
        self.add_widget(top)

        # Signals scroll area
        self.scroll = ScrollView(size_hint_y=0.35)
        self.signals_container = BoxLayout(orientation='vertical', size_hint_y=None)
        self.signals_container.bind(minimum_height=self.signals_container.setter('height'))
        self.scroll.add_widget(self.signals_container)
        self.add_widget(self.scroll)

        # Martingale status
        self.martingale_label = Label(
            text='Balance: 1000.00 | Bet: 50.00 | Losses: 0',
            size_hint_y=None, height=40, font_size=13,
            color=(0.2, 0.4, 0.8, 1)
        )
        self.add_widget(self.martingale_label)

        # Final signal
        self.final_label = Label(
            text='FINAL SIGNAL: HOLD',
            size_hint_y=None, height=50, font_size=18,
            bold=True, color=(0.5, 0.5, 0.5, 1)
        )
        self.add_widget(self.final_label)

        # Chart
        self.chart_image = Image(size_hint_y=0.4)
        self.add_widget(self.chart_image)

        Clock.schedule_interval(self.process_queue, 0.1)

    def toggle_analysis(self, instance):
        if self.is_running:
            self.is_running = False
            self.status_label.text = 'Status: stopped'
            self.run_btn.text = 'Start Analysis'
            return
        self.is_running = True
        self.status_label.text = 'Status: running'
        self.run_btn.text = 'Stop Analysis'
        self.martingale.reset()
        t = threading.Thread(target=self.run_analysis_loop, daemon=True)
        t.start()

    def run_analysis_loop(self):
        tf_map = {'1m': 1, '2m': 2, '3m': 3, '4m': 4, '5m': 5,
                  '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440, '1w': 10080}

        while self.is_running:
            pair_text = self.pair_spinner.text
            current_key = pair_text[0] if pair_text else 'e'
            tf = self.tf_spinner.text
            interval_minutes = tf_map.get(tf, 5)

            pair_info = PAIRS.get(current_key, PAIRS['e'])
            ticker_yf = pair_info['yf']
            ticker_ccxt = pair_info['ccxt']
            pair_inv = pair_info['investing']
            cg_id = pair_info.get('coingecko')
            gn_asset = pair_info.get('glassnode')
            forex_base = pair_info.get('forex_base')
            forex_target = pair_info.get('forex_target')

            signals = []

            # Source 1: Yahoo Finance
            df_yf = get_data_yfinance(ticker_yf, minutes=50)
            sig_yf = None
            if df_yf is not None and not df_yf.empty:
                df_yf_ind = compute_indicators(df_yf)
                if df_yf_ind is not None and not df_yf_ind.empty:
                    last_yf = df_yf_ind.iloc[-1]
                    sig_yf = generate_signal(last_yf, col_close="Close")
            if sig_yf:
                signals.append(("Yahoo Finance", sig_yf))

            # Source 2: CCXT or Forex API
            sig_src2 = None
            if forex_base and forex_target:
                forex_src_name = "Forex API"
                try:
                    df_forex, forex_src_name = get_data_forex_api(forex_base, forex_target, minutes=50)
                    if df_forex is not None and not df_forex.empty:
                        df_forex_ind = compute_indicators(df_forex)
                        if df_forex_ind is not None and not df_forex_ind.empty:
                            last_forex = df_forex_ind.iloc[-1]
                            sig_src2 = generate_signal(last_forex, col_close="close")
                        sig_forex_direct = get_signal_forex_api(forex_base, forex_target)
                        if sig_forex_direct and sig_forex_direct != "HOLD":
                            if sig_src2 and sig_src2 != sig_forex_direct:
                                sig_src2 = "HOLD"
                            elif not sig_src2:
                                sig_src2 = sig_forex_direct
                except Exception as e:
                    print(f"[Forex API] Error: {e}")
                if sig_src2:
                    signals.append((f"Forex API ({forex_src_name})", sig_src2))
            else:
                try:
                    df_ccxt = get_data_ccxt(ticker_ccxt, minutes=50)
                    if df_ccxt is not None and not df_ccxt.empty:
                        df_ccxt_ind = compute_indicators(df_ccxt)
                        if df_ccxt_ind is not None and not df_ccxt_ind.empty:
                            last_ccxt = df_ccxt_ind.iloc[-1]
                            sig_src2 = generate_signal(last_ccxt, col_close="close")
                except Exception as e:
                    print(f"[CCXT] Error: {e}")
                if sig_src2:
                    signals.append(("CCXT (OKX)", sig_src2))

            # Source 3: Investing (sim)
            df_inv = get_data_investing_simulated(pair_inv, interval_minutes, minutes_count=50)
            sig_inv = None
            if df_inv is not None and not df_inv.empty:
                df_inv_ind = compute_indicators(df_inv)
                if df_inv_ind is not None and not df_inv_ind.empty:
                    last_inv = df_inv_ind.iloc[-1]
                    sig_inv = generate_signal(last_inv, col_close="close")
            if sig_inv:
                signals.append(("Investing (sim)", sig_inv))

            # Source 4: TradingView (sim)
            sig_tv = None
            if df_inv is not None and len(df_inv) >= 2:
                sig_tv = generate_tradingview_like_signal(df_inv)
            if sig_tv:
                signals.append(("TradingView (sim)", sig_tv))

            # Source 5: CoinGecko
            sig_cg = None
            if cg_id:
                try:
                    sig_cg = get_signal_coingecko(cg_id)
                except Exception as e:
                    print(f"[CoinGecko] Error: {e}")
            if sig_cg:
                signals.append(("CoinGecko (API)", sig_cg))

            # Source 6: Glassnode
            sig_gn = None
            if gn_asset:
                try:
                    sig_gn = get_signal_glassnode(gn_asset)
                except Exception as e:
                    print(f"[Glassnode] Error: {e}")
            if sig_gn:
                signals.append(("Glassnode (API)", sig_gn))

            # Source 7: Samurai Algo
            sig_sa = None
            ref_df = df_inv if df_inv is not None else df_yf
            if ref_df is not None:
                sig_sa = get_signal_samurai_algo(ref_df)
            if sig_sa:
                signals.append(("Samurai Algo (sim)", sig_sa))

            # Source 8: TradeMaster Pro
            sig_tm = None
            if ref_df is not None:
                sig_tm = get_signal_trademaster_pro(ref_df)
            if sig_tm:
                signals.append(("TradeMaster Pro (sim)", sig_tm))

            # Consensus
            buy_count = sum(1 for _, s in signals if s == "BUY_SIGNAL")
            sell_count = sum(1 for _, s in signals if s == "SELL_SIGNAL")
            final_signal = "HOLD"
            if buy_count > sell_count and buy_count >= 2:
                final_signal = "BUY_SIGNAL"
            elif sell_count > buy_count and sell_count >= 2:
                final_signal = "SELL_SIGNAL"

            self.martingale.simulate_trade(final_signal)
            status = self.martingale.get_status()

            chart_data = None
            if df_inv is not None and not df_inv.empty:
                chart_data = {
                    "index": df_inv.index.tolist(),
                    "close": df_inv["close"].tolist(),
                    "ma_20": df_inv["ma_20"].tolist() if "ma_20" in df_inv.columns else None,
                }

            self.update_queue.put({
                "signals": signals,
                "final_signal": final_signal,
                "martingale_status": status,
                "chart_data": chart_data,
                "source_count": len(signals),
                "buy_count": buy_count,
                "sell_count": sell_count,
            })

            time.sleep(5)

    def process_queue(self, dt):
        try:
            while not self.update_queue.empty():
                update = self.update_queue.get_nowait()

                self.signals_container.clear_widgets()
                for src, sig in update["signals"]:
                    row = SignalRow(src, sig)
                    self.signals_container.add_widget(row)

                final = update["final_signal"]
                color = (0.5, 0.5, 0.5, 1)
                if final == "BUY_SIGNAL":
                    color = (0, 0.8, 0, 1)
                elif final == "SELL_SIGNAL":
                    color = (0.9, 0, 0, 1)
                self.final_label.text = (
                    f"FINAL SIGNAL: {final} "
                    f"(sources: {update['source_count']}, "
                    f"BUY: {update['buy_count']}, SELL: {update['sell_count']})"
                )
                self.final_label.color = color

                status = update["martingale_status"]
                self.martingale_label.text = (
                    f"Balance: {status['balance']:.2f} | "
                    f"Bet: {status['current_bet']:.2f} | "
                    f"Losses: {status['loss_streak']} | "
                    f"Max loss: {status['max_possible_loss']:.2f}"
                )

                chart_data = update["chart_data"]
                if chart_data is not None:
                    fig, ax = plt.subplots(figsize=(7, 3), dpi=100)
                    ax.plot(chart_data["index"], chart_data["close"], label="Price", color="blue")
                    if chart_data["ma_20"] is not None:
                        ma_series = chart_data["ma_20"]
                        if not all(pd.isna(x) for x in ma_series):
                            ax.plot(chart_data["index"], ma_series, label="MA(20)", color="orange", linestyle="--")
                    ax.set_title("Price and MA")
                    ax.set_xlabel("Time")
                    ax.set_ylabel("Price")
                    ax.legend(loc="upper left")
                    ax.grid(True, linestyle=":", alpha=0.5)
                    fig.tight_layout()
                    buf = BytesIO()
                    fig.savefig(buf, format='png')
                    buf.seek(0)
                    plt.close(fig)
                    self.chart_image.texture = CoreImage(buf, ext='png').texture

        except Exception as e:
            print(f"[GUI Update] Error: {e}")


class TradingApp(App):
    def build(self):
        return TradingApp()

    def on_stop(self):
        self.root.is_running = False


if __name__ == '__main__':
    TradingApp().run()
