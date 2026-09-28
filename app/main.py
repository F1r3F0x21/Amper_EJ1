import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf
from asyncua import Server, ua
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("amper")
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DATABASE_PATH", "/data/amper.sqlite3"))
POLL_SECONDS = max(30, int(os.getenv("POLL_SECONDS", "60")))
OPC_ENDPOINT = os.getenv("OPC_ENDPOINT", "opc.tcp://0.0.0.0:4840/amper/")
SYMBOL = "AMP.MC"
app_state = {"status": "Iniciando", "price": None, "volume": 0, "timestamp": None, "previous_close": None}


@contextmanager
def connect_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                timestamp TEXT PRIMARY KEY,
                price REAL NOT NULL,
                volume INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'Yahoo Finance'
            )"""
        )


def to_utc_iso(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def save_frame(frame) -> int:
    if frame is None or frame.empty or "Close" not in frame:
        return 0
    rows = []
    for timestamp, row in frame.iterrows():
        price = row.get("Close")
        if price is None or not float(price) > 0:
            continue
        volume = row.get("Volume", 0)
        rows.append((to_utc_iso(timestamp.to_pydatetime()), float(price), int(volume or 0)))
    with connect_db() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO prices(timestamp, price, volume) VALUES (?, ?, ?)", rows
        )
    return len(rows)


def seed_history() -> None:
    try:
        history = yf.Ticker(SYMBOL).history(period="1mo", interval="5m", auto_adjust=False)
        logger.info("Histórico inicial guardado: %s puntos", save_frame(history))
    except Exception:
        logger.exception("No se pudo descargar el histórico inicial")


def fetch_latest() -> dict:
    ticker = yf.Ticker(SYMBOL)
    intraday = ticker.history(period="1d", interval="1m", auto_adjust=False)
    if intraday is None or intraday.empty:
        raise RuntimeError("El proveedor no ha devuelto datos intradía")
    latest = intraday.iloc[-1]
    timestamp = intraday.index[-1].to_pydatetime()
    price = float(latest["Close"])
    if not price > 0:
        raise RuntimeError("El proveedor ha devuelto un precio no válido")
    volume = int(latest.get("Volume", 0) or 0)
    with connect_db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO prices(timestamp, price, volume) VALUES (?, ?, ?)",
            (to_utc_iso(timestamp), price, volume),
        )
    daily = ticker.history(period="5d", interval="1d", auto_adjust=False)
    closes = daily["Close"].dropna() if daily is not None and not daily.empty else []
    previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else float(closes.iloc[-1]) if len(closes) else None
    return {"price": price, "volume": volume, "timestamp": to_utc_iso(timestamp), "previous_close": previous_close}


async def poll_market(opc_nodes: dict) -> None:
    while True:
        try:
            market = await asyncio.to_thread(fetch_latest)
            change = market["price"] - market["previous_close"] if market["previous_close"] else 0.0
            percent = change / market["previous_close"] * 100 if market["previous_close"] else 0.0
            await opc_nodes["price"].write_value(ua.Variant(market["price"], ua.VariantType.Double))
            await opc_nodes["change"].write_value(ua.Variant(change, ua.VariantType.Double))
            await opc_nodes["percent"].write_value(ua.Variant(percent, ua.VariantType.Double))
            await opc_nodes["volume"].write_value(ua.Variant(market["volume"], ua.VariantType.UInt64))
            await opc_nodes["timestamp"].write_value(
                ua.Variant(datetime.fromisoformat(market["timestamp"]), ua.VariantType.DateTime)
            )
            await opc_nodes["status"].write_value("Conectado")
            app_state.update(market)
            app_state["status"] = "Conectado"
            logger.info("Precio actualizado: %.3f EUR", market["price"])
        except Exception as error:
            logger.warning("Error actualizando cotización: %s", error)
            app_state["status"] = "Sin conexión con el proveedor"
            await opc_nodes["status"].write_value(app_state["status"])
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await asyncio.to_thread(seed_history)
    server = Server()
    await server.init()
    server.set_endpoint(OPC_ENDPOINT)
    server.set_server_name("Amper Market Data")
    namespace = await server.register_namespace("https://amper.local/opcua/")
    amper = await server.nodes.objects.add_object(namespace, "Amper")
    opc_nodes = {
        "price": await amper.add_variable(namespace, "PriceEUR", 0.0),
        "change": await amper.add_variable(namespace, "ChangeEUR", 0.0),
        "percent": await amper.add_variable(namespace, "ChangePercent", 0.0),
        "volume": await amper.add_variable(namespace, "Volume", ua.Variant(0, ua.VariantType.UInt64)),
        "timestamp": await amper.add_variable(namespace, "TimestampUTC", datetime.now(timezone.utc)),
        "status": await amper.add_variable(namespace, "Status", "Iniciando"),
    }
    for node in opc_nodes.values():
        await node.set_writable(False)
    await server.start()
    poller = asyncio.create_task(poll_market(opc_nodes))
    try:
        yield
    finally:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        await server.stop()


app = FastAPI(title="Amper Market Watch", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/quote")
def get_quote():
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM prices ORDER BY timestamp DESC LIMIT 1").fetchone()
    if row is None:
        return {**app_state, "source": "Yahoo Finance", "poll_seconds": POLL_SECONDS}
    previous_close = app_state.get("previous_close")
    change = row["price"] - previous_close if previous_close else None
    change_percent = change / previous_close * 100 if change is not None else None
    return {
        "symbol": SYMBOL,
        "name": "Amper, S.A.",
        "currency": "EUR",
        "price": row["price"],
        "change": change,
        "change_percent": change_percent,
        "volume": row["volume"],
        "timestamp": row["timestamp"],
        "status": app_state["status"],
        "previous_close": previous_close,
        "source": "Yahoo Finance",
        "poll_seconds": POLL_SECONDS,
    }


@app.get("/api/history")
def get_history(period: str = Query("1d", pattern="^(1d|5d|1m)$")):
    durations = {"1d": timedelta(days=1), "5d": timedelta(days=5), "1m": timedelta(days=31)}
    cutoff = to_utc_iso(datetime.now(timezone.utc) - durations[period])
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT timestamp, price, volume FROM prices WHERE timestamp >= ? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
    return {"period": period, "points": [dict(row) for row in rows]}


@app.get("/health")
def health():
    return {"ok": True, "status": app_state["status"]}