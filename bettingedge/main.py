from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
import os

from backend.db.database import engine, Base
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BettingEdge", lifespan=lifespan)


@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "db": db_status}


frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")

app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.get("/{page}")
def serve_page(page: str):
    path = os.path.join(frontend_dir, f"{page}.html")
    if os.path.exists(path):
        return FileResponse(path)
    return FileResponse(os.path.join(frontend_dir, "index.html"))
