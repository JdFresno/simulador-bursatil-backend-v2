from sqlalchemy import Column, Integer, String, Float, DateTime
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    cash_balance = Column(Float, default=100000.0)

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    symbol = Column(String)
    quantity = Column(Integer)
    entry_price = Column(Float)
    reference_price = Column(Float) # <-- NUEVO CAMPO
    position_type = Column(String, default="SHORT")
    margin_locked = Column(Float)

class TradeHistory(Base):
    __tablename__ = "trade_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    symbol = Column(String)
    op_type = Column(String) # SELL_SHORT, COVER_SHORT
    quantity = Column(Integer)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    symbol = Column(String, index=True)
    name = Column(String)
    exchange = Column(String)
    
class Exchange(Base):
    __tablename__ = "exchanges"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # Ej: "Bolsa de Madrid"
    country = Column(String)                       # Ej: "España"
    symbol_suffix = Column(String)                 # Ej: ".MC" (para vincular con Yahoo)
    open_time = Column(String)                     # Ej: "09:00"
    close_time = Column(String)                    # Ej: "17:30"
    
    # Guardaremos los días como una cadena separada por comas: "0,1,2,3,4" 
    # donde 0=Lunes y 6=Domingo
    operating_days = Column(String, default="0,1,2,3,4") 
    timezone = Column(String, default="Europe/Madrid") # Muy importante para los horarios