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