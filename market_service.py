import os
import httpx
import yfinance as yf
import time
from datetime import datetime
import pytz
import models
import exchange_calendars as xcals
import pandas as pd


# --- CONFIGURACIÓN DE CACHÉ ---
# Guardaremos los datos así: { "AAPL": {"timestamp": 1234567, "data": {...}}, ... }
_stock_cache = {}
# Tiempo en segundos para considerar los datos como "frescos" (120 seg = 2 min)
CACHE_DURATION = 600 
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
# Diccionario para nombres y bolsas (Caché de larga duración)
_metadata_cache = {}

async def get_live_price(symbol: str):
    if TWELVE_DATA_KEY:
        url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_DATA_KEY}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    return float(data["price"])
        except: pass
    
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        return float(data['Close'].iloc[-1])
    except: return None

# Diccionario de mercados populares y sus sufijos en Yahoo Finance
MARKETS = {
    "España (IBEX 35)": ["SAN.MC", "ITX.MC", "BBVA.MC", "TEF.MC", "IBE.MC", "REP.MC", "GRF.MC", "AMS.MC"],
    "USA (Tecnología)": ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "NFLX"],
    "Alemania (DAX)": ["BMW.DE", "DAI.DE", "SAP.DE", "ALV.DE", "BAYN.DE", "VOW3.DE"],
    "ETFs Globales": [
        "SPY",        # S&P 500 (El más famoso)
        "QQQ",        # Nasdaq 100
        "IWM",        # Russell 2000 (Pequeñas empresas USA)
        "EEM",        # Mercados Emergentes
        "GLD",        # Oro
        "VUSA.L",     # S&P 500 en Euros (cotiza en Londres)
        "EXS1.DE"     # DAX ETF (cotiza en Alemania)
    ],
    "Cripto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"]
}

async def get_stocks_by_market(market_name: str):
    symbols = MARKETS.get(market_name, [])
    results = []
    
    for symbol in symbols:
        price = await get_live_price(symbol)
        if price:
            results.append({
                "symbol": symbol,
                "price": round(float(price), 2),
                "name": symbol.split('.')[0] # Nombre simplificado
            })
    return results
    
async def search_stocks(query: str):
    url = f"https://api.twelvedata.com/symbol_search?symbol={query}&apikey={TWELVE_DATA_KEY}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()
        
        results = []
        # Tomamos los primeros 10 resultados para no saturar
        for item in data.get("data", [])[:10]:
            # Obtenemos precio actual de cada resultado
            price = await get_live_price(item["symbol"])
            results.append({
                "symbol": item["symbol"],
                "name": item["instrument_name"],
                "exchange": item["exchange"],
                "price": price or 0.0
            })
        return results
        
async def get_history_data(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        # Obtenemos datos de 1 día con intervalo de 15 minutos
        df = ticker.history(period="1d", interval="15m")
        if not df.empty:
            # Convertimos la columna 'Close' en una lista de floats redondeados
            return [round(float(price), 2) for price in df['Close'].tolist()]
    except:
        return []
    return []
    
async def get_full_quote(symbol: str):
    now = time.time()
    symbol = symbol.upper()

    # 1. Comprobar Caché
    if symbol in _stock_cache:
        entry = _stock_cache[symbol]
        if now - entry["timestamp"] < CACHE_DURATION:
            return entry["data"]

    # 2. INTENTO CON TWELVE DATA (Fuente Principal)
    if TWELVE_DATA_KEY:
        try:
            # Pedimos quote (precios y estado) y time_series (gráfica)
            # Nota: Agrupamos para intentar ahorrar créditos
            async with httpx.AsyncClient() as client:
                # Obtenemos precio actual y metadatos
                quote_url = f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={TWELVE_DATA_KEY}"
                # Obtenemos serie histórica para la gráfica (intervalo 15m)
                series_url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=20&apikey={TWELVE_DATA_KEY}"
                
                quote_resp = await client.get(quote_url)
                series_resp = await client.get(series_url)
                
                q_data = quote_resp.json()
                s_data = series_resp.json()

                if "price" in q_data or "close" in q_data:
                    # Mapeo de Twelve Data a nuestro formato
                    res_data = {
                        "current_price": round(float(q_data.get("close") or q_data.get("price")), 2),
                        "high": round(float(q_data.get("high")), 2),
                        "low": round(float(q_data.get("low")), 2),
                        "name": q_data.get("name") or symbol,
                        "exchange": q_data.get("exchange") or "N/A",
                        "market_state": "OPEN" if q_data.get("is_market_open") else "CLOSED",
                        "history": [round(float(x["close"]), 2) for x in s_data.get("values", [])][::-1] # Invertimos para que sea cronológico
                    }
                    save_to_cache(symbol, res_data)
                    return res_data
        except Exception as e:
            print(f"Twelve Data falló o límite alcanzado para {symbol}, probando Yahoo...")

    # 3. RESPALDO CON YAHOO FINANCE (Si Twelve Data falla o no hay clave)
    return await get_yahoo_fallback(symbol)   

async def get_yahoo_fallback(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        # Pedimos el día actual con intervalo de 15m
        hist = ticker.history(period="1d", interval="15m")
        if hist.empty: return None
        
        info = ticker.info
        res_data = {
            "current_price": round(float(hist['Close'].iloc[-1]), 2),
            "high": round(float(hist['High'].max()), 2),
            "low": round(float(hist['Low'].min()), 2),
            "name": info.get("longName") or symbol,
            "exchange": info.get("exchange", "N/A"),
            "market_state": info.get("marketState", "CLOSED"),
            "history": [round(float(p), 2) for p in hist['Close'].tolist()]
        }
        save_to_cache(symbol, res_data)
        return res_data
    except Exception as e:
        print(f"Yahoo Finance también falló para {symbol}: {e}")
        return None

def save_to_cache(symbol, data):
    _stock_cache[symbol] = {
        "timestamp": time.time(),
        "data": data
    }
    

def is_market_open(exchange: models.Exchange):
    # Obtener la hora actual en la zona horaria de esa bolsa
    tz = pytz.timezone(exchange.timezone)
    now = datetime.now(tz)
    
    # Verificar si hoy es día operativo (ej: "0,1,2,3,4")
    current_day = str(now.weekday())
    if current_day not in exchange.operating_days.split(","):
        return False
        
    # Verificar si estamos dentro del horario (HH:MM)
    current_time = now.strftime("%H:%M")
    return exchange.open_time <= current_time <= exchange.close_time
    
import pandas as pd
import exchange_calendars as xcals

def calculate_market_status(exchange: models.Exchange):
    try:
        if not exchange or not hasattr(exchange, 'mic_code') or not exchange.mic_code:
            return "UNKNOWN"

        # Obtenemos el calendario
        calendar = xcals.get_calendar(exchange.mic_code)
        
        # --- CORRECCIÓN CRÍTICA ---
        # En lugar de usar utcnow() o is_open_now(), usamos un Timestamp 
        # localizado explícitamente para evitar el error del atributo '.key'
        ahora_utc = pd.Timestamp.now(tz='UTC')
        
        # 1. ¿Es día de sesión?
        if not calendar.is_session(ahora_utc.floor("D")):
            return "HOLIDAY"
        
        # 2. ¿Está abierta? 
        # Usamos 'is_open_on_minute' que es más estable que 'is_open_now'
        esta_abierta = calendar.is_open_on_minute(ahora_utc)
        
        return "OPEN" if esta_abierta else "CLOSED"

    except Exception as e:
        # Esto es lo que veía en sus logs
        print(f"Error en calendario para {exchange.name}: {e}")
        return "CLOSED"
    
async def get_exchange_by_symbol(db, symbol: str):
    """
    Identifica a qué bolsa pertenece un símbolo por su sufijo.
    Ej: SAN.MC -> Bolsa de Madrid (.MC)
    """
    if "." in symbol:
        suffix = "." + symbol.split(".")[-1]
    else:
        suffix = "" # NYSE / NASDAQ no suelen llevar sufijo en nuestra lógica
        
    return db.query(models.Exchange).filter(models.Exchange.symbol_suffix == suffix).first()
    
    
    
async def get_batch_quotes(symbols: list):
    """
    Obtiene precios e historia de una lista de símbolos en UNA SOLA petición.
    """
    if not symbols:
        return {}

    try:
        # Convertimos la lista ["AAPL", "TSLA"] en un string "AAPL TSLA"
        symbols_str = " ".join(symbols)
        
        # Descargamos datos de 1 día con intervalo de 15m para todos los tickers
        # group_by='ticker' es clave para organizar los datos por acción
        df = yf.download(
            tickers=symbols_str, 
            period="1d", 
            interval="15m", 
            group_by='ticker',
            progress=False
        )

        results = {}
        for symbol in symbols:
            # Extraemos los datos de cada símbolo del DataFrame global
            try:
                # Si es un solo símbolo, yfinance devuelve una estructura distinta
                ticker_df = df[symbol] if len(symbols) > 1 else df
                
                if not ticker_df.empty:
                    # Filtramos filas sin datos (NaN)
                    ticker_df = ticker_df.dropna()
                    
                    last_price = float(ticker_df['Close'].iloc[-1])
                    high_day = float(ticker_df['High'].max())
                    low_day = float(ticker_df['Low'].min())
                    history = [round(float(p), 2) for p in ticker_df['Close'].tolist()]

                    results[symbol] = {
                        "current_price": round(last_price, 2),
                        "high": round(high_day, 2),
                        "low": round(low_day, 2),
                        "history": history
                    }
            except:
                continue
        return results
    except Exception as e:
        print(f"Error en Batch Download: {e}")
        return {}
        
        
async def get_metadata_safe(symbol: str):
    """
    Obtiene el nombre y la bolsa intentando NO molestar a Yahoo Finance.
    """
    symbol = symbol.upper()
    
    # 1. Si ya lo conocemos de esta sesión, lo devolvemos al instante
    if symbol in _metadata_cache:
        return _metadata_cache[symbol]

    # 2. Si no, intentamos con Twelve Data (que es más generoso con los nombres)
    if TWELVE_DATA_KEY:
        try:
            url = f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={TWELVE_DATA_KEY}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=3)
                if resp.status_code == 200:
                    d = resp.json()
                    meta = {
                        "name": d.get("name", symbol),
                        "exchange": d.get("exchange", "N/A")
                    }
                    _metadata_cache[symbol] = meta
                    return meta
        except: pass

    # 3. Solo si todo lo anterior falla, vamos a Yahoo, pero con mucho cuidado
    try:
        t = yf.Ticker(symbol)
        # Usamos fast_info si está disponible para no disparar el bloqueo
        meta = {
            "name": t.info.get("longName", symbol),
            "exchange": t.info.get("exchange", "N/A")
        }
        _metadata_cache[symbol] = meta
        return meta
    except:
        return {"name": symbol, "exchange": "N/A"}