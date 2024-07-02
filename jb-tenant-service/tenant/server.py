from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth_api import auth_app

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/auth", auth_app)
