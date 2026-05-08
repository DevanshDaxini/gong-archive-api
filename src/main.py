import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import Config
from src.endpoints import router
from src.index import build_index

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()
    logger.info(f"TIME_OFFSET: {config.offset_days} days")
    index = build_index(config)
    logger.info(f"Index built: {len(index)} calls indexed")
    app.state.config = config
    app.state.index = index
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
