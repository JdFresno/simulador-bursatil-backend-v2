from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import models, database, market_service
from pydantic import BaseModel
from database import engine
import datetime

models.Base.metadata.create_all(bind=database.engine)
app = FastAPI()

class TradeRequest(BaseModel):
    user_id: int
    symbol: str
    quantity: int

def get_db():
    db = database.SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/trade/short/open")
async def open_short(trade: TradeRequest, db: Session = Depends(get_db)):
    price = await market_service.get_live_price(trade.symbol)
    if not price: raise HTTPException(status_code=404, detail="Símbolo no encontrado")
    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    total_val = price * trade.quantity
    if user.cash_balance < (total_val * 0.5): raise HTTPException(status_code=400, detail="Margen insuficiente")
    
    user.cash_balance += total_val
    db.add(models.Position(user_id=user.id, symbol=trade.symbol.upper(), quantity=trade.quantity, entry_price=price, margin_locked=total_val*0.5))
    db.commit()
    return {"status": "success", "price": price}

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    # ... (lógica de creación de usuario si no existe) ...

    positions = db.query(models.Position).filter(models.Position.user_id == user_id).all()
    portfolio_data = []

    for p in positions:
        # A. Obtener datos de precio (Yahoo/Twelve)
        details = await market_service.get_full_quote(p.symbol)
        
        # B. Obtener reglas de la bolsa desde NUESTRA Base de Datos
        exchange_info = await market_service.get_exchange_by_symbol(db, p.symbol)
        
        # C. Calcular estado localmente
        if exchange_info:
            local_status = market_service.calculate_market_status(exchange_info)
            exchange_name = exchange_info.name
        else:
            local_status = "UNKNOWN"
            exchange_name = "N/A"

        if details:
            portfolio_data.append({
                "symbol": p.symbol,
                "name": details.get("name", p.symbol),
                "exchange": exchange_name,
                "market_state": local_status, # <--- Estado calculado por nosotros
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": details["current_price"],
                "high": details["high"],
                "low": details["low"],
                "position_type": p.position_type,
                "history": details.get("history", [])
            })
            
    return {"cash_balance": round(user.cash_balance, 2), "positions": portfolio_data}
    
@app.get("/")
def read_root():
    return {"message": "Servidor funcionando correctamente"}
    
@app.get("/")
async def read_root():
    return {"status": "ok", "message": "Servidor de Simulación Activo"}
    
@app.on_event("startup")
def startup_populate():
    db = database.SessionLocal()
    # Verifica si el usuario 1 existe, si no, lo crea
    user = db.query(models.User).filter(models.User.id == 1).first()
    if not user:
        user = models.User(id=1, username="demo", cash_balance=100000.0)
        db.add(user)
        db.commit()
    db.close()
    
    
@app.post("/trade/short/close")
async def close_short(trade: TradeRequest, db: Session = Depends(get_db)):
    # 1. Buscar la posición abierta del usuario
    pos = db.query(models.Position).filter(
        models.Position.user_id == trade.user_id,
        models.Position.symbol == trade.symbol.upper()
    ).first()

    if not pos:
        raise HTTPException(status_code=404, detail="No tienes una posición abierta en este valor")

    # 2. Obtener el precio actual de mercado (Yahoo/Twelve)
    current_price = await market_service.get_live_price(trade.symbol)
    if not current_price:
        raise HTTPException(status_code=400, detail="No se pudo obtener el precio para cerrar")

    # 3. Lógica financiera: Compramos las acciones para devolverlas
    cost_to_cover = current_price * pos.quantity
    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    
    # Restamos el dinero que nos cuesta recomprar las acciones
    user.cash_balance -= cost_to_cover
    
    # 4. Registrar en el historial y eliminar la posición
    history = models.TradeHistory(
        user_id=user.id, symbol=trade.symbol.upper(),
        op_type="COVER_SHORT", quantity=pos.quantity, price=current_price
    )
    
    db.delete(pos)
    db.add(history)
    db.commit()
    
    return {"status": "success", "profit_loss": (pos.entry_price - current_price) * pos.quantity}
    
@app.post("/trade/long/open")
async def open_long(trade: TradeRequest, db: Session = Depends(get_db)):
    price = await market_service.get_live_price(trade.symbol)
    if not price: raise HTTPException(status_code=404, detail="Símbolo no encontrado")

    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    total_cost = price * trade.quantity

    if user.cash_balance < total_cost:
        raise HTTPException(status_code=400, detail="Saldo insuficiente para comprar")

    # En una COMPRA, restamos el dinero del saldo
    user.cash_balance -= total_cost
    
    new_pos = models.Position(
        user_id=user.id, symbol=trade.symbol.upper(),
        quantity=trade.quantity, entry_price=price,
        position_type="LONG", # Identificador de compra normal
        margin_locked=0.0
    )
    
    db.add(new_pos)
    db.commit()
    return {"status": "success", "price": price}
    
    
@app.get("/stocks/markets")
def get_available_markets():
    return list(market_service.MARKETS.keys())

@app.get("/stocks/list/{market}")
async def get_market_stocks(market: str):
    return await market_service.get_stocks_by_market(market)
    
    
MARKETS = {
    "España (IBEX 35)": ["SAN.MC", "ITX.MC", "BBVA.MC", "TEF.MC"],
    "USA (Tecnología)": ["AAPL", "TSLA", "NVDA", "MSFT"],
    "Cripto": ["BTC-USD", "ETH-USD"]
}

@app.get("/stocks/markets")
def get_available_markets():
    # Esto devuelve ["España (IBEX 35)", "USA (Tecnología)", "Cripto"]
    return list(MARKETS.keys())
    
    
@app.get("/stocks/search")
async def search(query: str):
    return await market_service.search_stocks(query)

@app.post("/favorites/add")
def add_favorite(user_id: int, symbol: str, name: str, exchange: str, db: Session = Depends(get_db)):
    # Evitar duplicados
    exists = db.query(models.Favorite).filter(models.Favorite.user_id == user_id, models.Favorite.symbol == symbol).first()
    if not exists:
        new_fav = models.Favorite(user_id=user_id, symbol=symbol, name=name, exchange=exchange)
        db.add(new_fav)
        db.commit()
    return {"status": "success"}
  
@app.get("/favorites/{user_id}")
async def get_favorites(user_id: int, db: Session = Depends(get_db)):
    favs = db.query(models.Favorite).filter(models.Favorite.user_id == user_id).all()
    results = []
    for f in favs:
        # Obtenemos el precio en vivo para cada favorito
        price = await market_service.get_live_price(f.symbol)
        results.append({
            "id": f.id, # Necesario para poder borrarlo
            "symbol": f.symbol,
            "name": f.name,
            "exchange": f.exchange,
            "price": price or 0.0
        })
    return results

@app.delete("/favorites/{fav_id}")
def delete_favorite(fav_id: int, db: Session = Depends(get_db)):
    fav = db.query(models.Favorite).filter(models.Favorite.id == fav_id).first()
    if fav:
        db.delete(fav)
        db.commit()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="No encontrado")
    
@app.get("/ping")
async def ping():
    """
    Endpoint simple para verificar la salud del servidor.
    Devuelve el estado y la hora actual del servidor.
    """
    return {
        "status": "online",
        "message": "pong",
        "server_time": datetime.datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }
    
@app.on_event("startup")
def startup_populate():
    db = database.SessionLocal()
    try:
        # 1. Crear usuario demo si no existe (ya lo teníamos)
        if not db.query(models.User).filter(models.User.id == 1).first():
            db.add(models.User(id=1, username="inversor_demo", cash_balance=100000.0))

        # 2. Crear bolsas de valores si la tabla está vacía
        if not db.query(models.Exchange).first():
            markets = [
                models.Exchange(
                    name="Bolsa de Madrid", country="España", symbol_suffix=".MC",
                    open_time="09:00", close_time="17:30", operating_days="0,1,2,3,4",
                    timezone="Europe/Madrid"
                ),
                models.Exchange(
                    name="NYSE", country="USA", symbol_suffix="",
                    open_time="09:30", close_time="16:00", operating_days="0,1,2,3,4",
                    timezone="America/New_York"
                ),
                models.Exchange(
                    name="XETRA", country="Alemania", symbol_suffix=".DE",
                    open_time="09:00", close_time="17:30", operating_days="0,1,2,3,4",
                    timezone="Europe/Berlin"
                )
            ]
            db.add_all(markets)
            db.commit()
    finally:
        db.close()
        
@app.get("/stocks/status/{exchange_id}")
async def get_status(exchange_id: int, db: Session = Depends(get_db)):
    exchange = db.query(models.Exchange).filter(models.Exchange.id == exchange_id).first()
    if not exchange:
        return {"error": "Bolsa no encontrada"}
    
    # Llamamos a la función que acabamos de crear en el otro fichero
    abierto = market_service.is_market_open(exchange)
    
    return {
        "exchange": exchange.name,
        "is_open": abierto
    }

