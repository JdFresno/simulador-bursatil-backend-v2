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