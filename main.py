from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import models, database, market_service
from pydantic import BaseModel
from database import engine

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
    # 1. Buscamos al usuario
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    # 2. SI NO EXISTE, LO CREAMOS AL VUELO
    if user is None:
        user = models.User(id=user_id, username=f"usuario_{user_id}", cash_balance=100000.0)
        db.add(user)
        db.commit()
        db.refresh(user) # Recargamos para que tenga los datos frescos

    # 3. Buscamos sus posiciones
    positions = db.query(models.Position).filter(models.Position.user_id == user_id).all()
    
    portfolio_data = []
    for p in positions:
        quote = await market_service.get_full_quote(p.symbol) # Llamada a la nueva función
        history = await market_service.get_history_data(p.symbol)
        
        if quote:
            portfolio_data.append({
                "symbol": p.symbol,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": quote["current_price"],
                "high": quote["high"],
                "low": quote["low"],
                "position_type": p.position_type,
                "history": history
            })
    return {"cash_balance": user.cash_balance, "positions": portfolio_data}
    
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