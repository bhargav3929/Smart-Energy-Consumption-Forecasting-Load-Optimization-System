"""Convenience launcher: python run.py  ->  http://127.0.0.1:8005"""
import os

import uvicorn

os.environ.setdefault("PORT", "8005")

HOST = "127.0.0.1"
PORT = 8005

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT)
