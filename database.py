import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Obtener la URL de la variable de entorno
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Validación y limpieza de la URL
if not SQLALCHEMY_DATABASE_URL:
    # Si no hay variable (local), usamos SQLite
    SQLALCHEMY_DATABASE_URL = "sqlite:///./trading_app.db"
else:
    # Si la URL empieza por postgres://, cambiar a postgresql:// (Requerido por SQLAlchemy)
    if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Configuración del motor (Engine)
# Solo añadimos check_same_thread si es SQLite
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()