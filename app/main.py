from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.config import settings
from app.routers import auth, games, possessions, users, players

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Annotation API")

# In production, replace "*" with your actual frontend origin(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=settings.upload_dir), name="media")

app.include_router(auth.router)
app.include_router(games.router)
app.include_router(possessions.router)
app.include_router(users.router)
app.include_router(players.router)


@app.get("/health")
def health():
    return {"status": "ok"}
