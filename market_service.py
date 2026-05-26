import os
import httpx
import yfinance as yf

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")

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
    try:
        ticker = yf.Ticker(symbol)
        # Obtenemos la información general (esto contiene el nombre y la bolsa)
        info = ticker.info
        
        # Obtenemos los datos de precio del día
        data = ticker.history(period="1d")
        
        if not data.empty:
            return {
                "current_price": round(float(data['Close'].iloc[-1]), 2),
                "high": round(float(data['High'].iloc[-1]), 2),
                "low": round(float(data['Low'].iloc[-1]), 2),
                "name": info.get("longName", symbol), # Nombre de la empresa
                "exchange": info.get("exchange", "N/A"), # Siglas de la bolsa (NASDAQ, MC...)
                "market_state": info.get("marketState", "CLOSED") # OPEN, CLOSED, PRE, POST...
            }
    except Exception as e:
        print(f"Error en yfinance: {e}")
        return None