from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import models, database, market_service
from pydantic import BaseModel
import datetime
import asyncio
import pandas as pd
import exchange_calendars as xcals

# Inicialización de la base de datos
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Simulador Bursátil API v2")

# --- ESQUEMAS DE DATOS ---
class TradeRequest(BaseModel):
    user_id: int
    symbol: str
    quantity: int
    trailing_stop: float = 0.5 # Valor por defecto

# --- DEPENDENCIA DE DB ---
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # 1. Lanzar tarea de refresco por hora en segundo plano
    asyncio.create_task(scheduled_market_refresh())
    
    # 2. Abrir sesión de base de datos
    db = database.SessionLocal()
    try:
        # --- A. Crear usuario maestro si no existe ---
        if not db.query(models.User).filter(models.User.id == 1).first():
            db.add(models.User(id=1, username="demo", cash_balance=100000.0))
        
        # --- B. Sincronizar / Crear bolsas de valores ---
        # Definimos los datos maestros que queremos tener
        master_markets = [
            {
                "name": "Bolsa de Madrid", "country": "España", "suffix": ".MC",
                "mic": "XMAD", "open": "09:00", "close": "17:30", "tz": "Europe/Madrid"
            },
            {
                "name": "NYSE", "country": "USA", "suffix": "",
                "mic": "XNYS", "open": "15:30", "close": "22:00", "tz": "America/New_York"
            },
            {
                "name": "XETRA", "country": "Alemania", "suffix": ".DE",
                "mic": "XETR", "open": "09:00", "close": "17:30", "tz": "Europe/Berlin"
            }
        ]

        for market in master_markets:
            # Buscamos si la bolsa ya existe por su nombre
            existing_exchange = db.query(models.Exchange).filter(models.Exchange.name == market["name"]).first()
            
            if not existing_exchange:
                # Si no existe, la creamos de cero con el mic_code
                print(f"INFO: Creando bolsa {market['name']}...")
                db.add(models.Exchange(
                    name=market["name"], country=market["country"], 
                    symbol_suffix=market["suffix"], mic_code=market["mic"], 
                    open_time=market["open"], close_time=market["close"], 
                    timezone=market["tz"]
                ))
            else:
                # SI YA EXISTE: Nos aseguramos de que el mic_code esté grabado
                # Esto arregla el error de las bolsas que se crearon antiguas sin mic_code
                if not existing_exchange.mic_code:
                    print(f"INFO: Actualizando mic_code para {market['name']}...")
                    existing_exchange.mic_code = market["mic"]

        db.commit()
        print("INFO: Sincronización de inicio completada con éxito.")

    except Exception as e:
        print(f"ERROR en startup_event: {e}")
        db.rollback()
    finally:
        db.close()

# --- ENDPOINTS DE CARTERA Y SALDOS ---

@app.get("/portfolio/{user_id}")
async def get_portfolio(user_id: int, db: Session = Depends(get_db)):
    # 1. Buscar o crear usuario
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        user = models.User(id=user_id, username=f"usuario_{user_id}", cash_balance=100000.0)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 2. Obtener posiciones del usuario
    positions = db.query(models.Position).filter(models.Position.user_id == user_id).all()
    
    # 3. PETICIÓN ÚNICA AL MERCADO (Batch) para todos los precios y gráficas
    symbols_list = list(set([p.symbol for p in positions]))
    batch_market_data = await market_service.get_batch_quotes(symbols_list)
    
    # 4. PRE-CARGAR LAS BOLSAS para calcular el estado localmente
    all_exchanges = db.query(models.Exchange).all()
    exchange_map = {ex.symbol_suffix: ex for ex in all_exchanges}
    
    # Acumuladores para los 5 saldos solicitados
    total_invested = 0.0
    total_pnl = 0.0
    pos_pnl_only = 0.0
    neg_pnl_only = 0.0

    portfolio_data = []
    updated_db = False 

    for p in positions:
        # A. Datos Dinámicos: Precios y Historia (Vienen del Batch de Yahoo)
        data = batch_market_data.get(p.symbol)
        
        # B. Datos Estáticos: Nombre y Bolsa (Vienen de nuestra BBDD AssetMetadata)
        # Esta función busca en Neon; si no existe, busca en TwelveData UNA VEZ y guarda
        metadata = await market_service.get_metadata_db(db, p.symbol)
        db.commit()
        if data:
            current = data["current_price"]
            tipo = str(p.position_type).strip().upper()
            
            # --- CÁLCULOS DE PATRIMONIO ---
            inversion_inicial = p.entry_price * p.quantity
            total_invested += inversion_inicial

            if tipo in ["LARGO", "LONG"]:
                pnl = (current - p.entry_price) * p.quantity
            else: # CORTO / SHORT
                pnl = (p.entry_price - current) * p.quantity
            
            total_pnl += pnl
            if pnl > 0: pos_pnl_only += pnl
            else: neg_pnl_only += pnl

            # --- LÓGICA DE REFERENCIA DINÁMICA ---
            if not p.reference_price or p.reference_price == 0:
                p.reference_price = p.entry_price
                updated_db = True

            if tipo in ["LARGO", "LONG"]:
                if current > p.reference_price:
                    p.reference_price = current
                    updated_db = True
                limit_price = p.reference_price * (1 - (p.trailing_stop_percent / 100))
                alert = current <= limit_price
            else: # CORTO / SHORT
                if current < p.reference_price:
                    p.reference_price = current
                    updated_db = True
                limit_price = p.reference_price * (1 + (p.trailing_stop_percent / 100))
                alert = current >= limit_price

            # --- CÁLCULO LOCAL DEL ESTADO DE LA BOLSA ---
            suffix = "." + p.symbol.split(".")[-1] if "." in p.symbol else ""
            ex_info = exchange_map.get(suffix)
            local_status = market_service.calculate_market_status(ex_info) if ex_info else "UNKNOWN"

            portfolio_data.append({
                "symbol": p.symbol,
                "name": metadata.get("name", p.symbol),
                "exchange": ex_info.name if ex_info else "N/A",
                "market_state": local_status,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "reference_price": p.reference_price,
                "current_price": current,
                "pnl": round(pnl, 2),
                "high": data["high"],
                "low": data["low"],
                "trailing_stop_percent": p.trailing_stop_percent,
                "stop_price": round(limit_price, 2),
                "is_alert_active": alert,
                "position_type": tipo,
                "history": data["history"]
            })
            
    if updated_db:
        db.commit()    
            
    # --- RESPUESTA CON LOS 5 SALDOS ---
    cash = user.cash_balance
    return {
        "cash_balance": round(cash, 2),                                   # 1. Dinero disponible
        "total_invested": round(total_invested, 2),                      # 2. Total Invertido
        "invested_plus_gains": round(total_invested + pos_pnl_only, 2),  # 3. Invertido + ganancias
        "invested_plus_losses": round(total_invested + neg_pnl_only, 2), # 4. Invertido + pérdidas
        "total_liquidation": round(cash + total_invested + total_pnl, 2), # 5. Total Liquidación (Neto)
        "positions": portfolio_data
    }

# --- ENDPOINTS DE OPERACIONES ---

@app.post("/trade/long/open")
async def open_long(trade: TradeRequest, db: Session = Depends(get_db)):
    price = await market_service.get_live_price(trade.symbol)
    if not price: raise HTTPException(status_code=404, detail="No disponible")
    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    cost = price * trade.quantity
    if user.cash_balance < cost: raise HTTPException(status_code=400, detail="Saldo insuficiente")
    
    user.cash_balance -= cost
    db.add(models.Position(user_id=user.id, symbol=trade.symbol.upper(), quantity=trade.quantity, 
                           entry_price=price, reference_price=price, position_type="LONG", trailing_stop_percent=0.5))
    db.commit()
    return {"status": "success"}

@app.post("/trade/short/open")
async def open_short(trade: TradeRequest, db: Session = Depends(get_db)):
    price = await market_service.get_live_price(trade.symbol)
    if not price: raise HTTPException(status_code=404, detail="No disponible")
    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    val = price * trade.quantity
    if user.cash_balance < (val * 0.5): raise HTTPException(status_code=400, detail="Margen insuficiente")
    
    user.cash_balance += val
    db.add(models.Position(user_id=user.id, symbol=trade.symbol.upper(), quantity=trade.quantity, 
                           entry_price=price, reference_price=price, position_type="SHORT", margin_locked=val*0.5, trailing_stop_percent=0.5))
    db.commit()
    return {"status": "success"}

@app.post("/trade/short/close")
async def close_position(trade: TradeRequest, db: Session = Depends(get_db)):
    pos = db.query(models.Position).filter(models.Position.user_id == trade.user_id, models.Position.symbol == trade.symbol.upper()).first()
    if not pos: raise HTTPException(status_code=404, detail="Sin posición")
    
    current_price = await market_service.get_live_price(trade.symbol)
    user = db.query(models.User).filter(models.User.id == trade.user_id).first()
    
    if pos.position_type in ["LARGO", "LONG"]:
        user.cash_balance += (current_price * pos.quantity)
    else:
        user.cash_balance -= (current_price * pos.quantity)
    
    db.delete(pos)
    db.commit()
    return {"status": "success"}

# --- ENDPOINTS DE MERCADOS Y BÚSQUEDA ---

@app.get("/stocks/markets")
def get_markets(db: Session = Depends(get_db)):
    # 1. Obtenemos todos los objetos de la base de datos
    exchanges = db.query(models.Exchange).all()
    
    # 2. EXTRAEMOS SOLO EL NOMBRE (String) para que Android no explote
    # Esto genera una lista de textos: ["Bolsa de Madrid", "NYSE", "XETRA"]
    return [ex.name for ex in exchanges]

@app.get("/stocks/list/{market_name}")
async def get_market_stocks(market_name: str):
    # Usamos las listas de símbolos predefinidas en market_service
    return await market_service.get_stocks_by_market(market_name)

@app.get("/stocks/search")
async def search(query: str):
    return await market_service.search_stocks(query)

@app.get("/exchanges/details")
async def get_exchanges_details(db: Session = Depends(get_db)):
    exchanges = db.query(models.Exchange).all()
    results = []
    for ex in exchanges:
        status = market_service.calculate_market_status(ex)
        # Obtenemos festivos automáticamente de la librería exchange_calendars
        try:
            cal = xcals.get_calendar(ex.mic_code)
            hols = [{"date": h.strftime("%Y-%m-%d"), "desc": "Festivo oficial"} 
                    for h in cal.adhoc_holidays if h.year == datetime.datetime.now().year][:3]
        except: hols = []

        results.append({
            "name": ex.name, "country": ex.country, "open_time": ex.open_time,
            "close_time": ex.close_time, "timezone": ex.timezone, "status": status,
            "next_holidays": hols
        })
    return results

# --- FAVORITOS ---
@app.get("/favorites/{user_id}")
async def get_favorites(user_id: int, db: Session = Depends(get_db)):
    favs = db.query(models.Favorite).filter(models.Favorite.user_id == user_id).all()
    results = []
    for f in favs:
        price = await market_service.get_live_price(f.symbol)
        results.append({"id": f.id, "symbol": f.symbol, "name": f.name, "exchange": f.exchange, "price": price or 0.0})
    return results

@app.post("/favorites/add")
def add_favorite(user_id: int, symbol: str, name: str, exchange: str, db: Session = Depends(get_db)):
    if not db.query(models.Favorite).filter(models.Favorite.user_id == user_id, models.Favorite.symbol == symbol).first():
        db.add(models.Favorite(user_id=user_id, symbol=symbol, name=name, exchange=exchange))
        db.commit()
    return {"status": "success"}

@app.delete("/favorites/{fav_id}")
def delete_favorite(fav_id: int, db: Session = Depends(get_db)):
    fav = db.query(models.Favorite).filter(models.Favorite.id == fav_id).first()
    if fav:
        db.delete(fav)
        db.commit()
        return {"status": "deleted"}
    return {"status": "not_found"}

# --- UTILIDADES ---
@app.get("/ping")
async def ping():
    return {"status": "online", "server_time": datetime.datetime.utcnow().isoformat()}

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend Simulador Activo"}

# --- TAREA PROGRAMADA ---
async def scheduled_market_refresh():
    while True:
        await asyncio.sleep(3600)
        db = database.SessionLocal()
        try:
            positions = db.query(models.Position).all()
            symbols = list(set([p.symbol for p in positions]))
            batch = await market_service.get_batch_quotes(symbols)
            for p in positions:
                data = batch.get(p.symbol)
                if data:
                    curr = data["current_price"]
                    tipo = str(p.position_type).strip().upper()
                    if tipo in ["LONG", "LARGO"] and curr > p.reference_price: p.reference_price = curr
                    elif tipo in ["SHORT", "CORTO"] and curr < p.reference_price: p.reference_price = curr
            db.commit()
        except: pass
        finally: db.close()