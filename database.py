import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading_app.db")

if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# --- CONFIGURACIÓN PARA EVITAR CORTES DE CONEXIÓN ---
if "postgresql" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        # 1. Verifica la conexión antes de usarla (imprescindible para Neon)
        pool_pre_ping=True,
        # 2. Cierra y recrea conexiones cada 5 minutos (300 seg) 
        # para que no lleguen al tiempo de espera de Neon/Render
        pool_recycle=300,
        # 3. Controla cuántas conexiones mantenemos abiertas
        pool_size=5,
        max_overflow=10
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()