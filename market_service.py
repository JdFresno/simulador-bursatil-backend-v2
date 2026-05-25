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
    
    
# En market_service.py

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
                "price": price,
                "name": symbol.split('.')[0] # Nombre simplificado
            })
    return results