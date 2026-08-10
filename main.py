from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r") as f:
        return f.read()

@app.get("/health")
def health_check():
    return {"status": "healthy"}