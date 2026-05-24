from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import models, database, market_service
from pydantic import BaseModel

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
    positions = db.query(models.Position).filter(models.Position.user_id == user_id).all()
    # (Lógica de consolidación de precios actuales aquí)
    return {"cash_balance": user.cash_balance, "positions": positions}
    
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