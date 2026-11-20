"""Convenience launcher: python run.py  ->  http://127.0.0.1:8005 (HOST/PORT come from .env)"""
import uvicorn

from app import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)
