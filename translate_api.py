"""
Fast translation API server using Ollama + gemma3:1b
Optimized for low latency with connection pooling and streaming.

Usage:
    pip install fastapi uvicorn httpx
    python translate_api.py
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "translator")

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(
        base_url=OLLAMA_URL,
        timeout=httpx.Timeout(60.0, connect=5.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    # Warm up: load model into memory
    try:
        await http_client.post("/api/generate", json={
            "model": MODEL_NAME,
            "prompt": "Hi",
            "options": {"num_predict": 1},
        })
    except httpx.ConnectError:
        print("Warning: Ollama not running. Start with: ollama serve")
    yield
    await http_client.aclose()


app = FastAPI(title="Translation API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LANG_NAMES = {
    "ja": "Japanese", "en": "English", "zh": "Chinese",
    "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "pt": "Portuguese", "it": "Italian",
    "ru": "Russian", "ar": "Arabic", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian", "nl": "Dutch",
}


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    target: str = Field(..., description="Target language code (e.g. ja, en, zh)")
    source: str | None = Field(None, description="Source language code (auto-detect if omitted)")
    stream: bool = Field(False, description="Stream the response")


class TranslateResponse(BaseModel):
    translation: str
    target: str
    elapsed_ms: float


class BatchRequest(BaseModel):
    texts: list[str] = Field(..., min_items=1, max_items=50)
    target: str
    source: str | None = None


class BatchResponse(BaseModel):
    translations: list[str]
    target: str
    elapsed_ms: float


def build_prompt(text: str, target: str, source: str | None = None) -> str:
    target_name = LANG_NAMES.get(target, target)
    if source:
        source_name = LANG_NAMES.get(source, source)
        return f"Translate from {source_name} to {target_name}. Output only the translation:\n\n{text}"
    return f"Translate to {target_name}. Output only the translation:\n\n{text}"


async def generate(prompt: str, stream: bool = False):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 20,
            "num_predict": 512,
            "num_ctx": 1024,
        },
    }
    if stream:
        return await http_client.post("/api/generate", json=payload)
    resp = await http_client.post("/api/generate", json=payload)
    resp.raise_for_status()
    return resp.json()["response"].strip()


@app.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    prompt = build_prompt(req.text, req.target, req.source)

    if req.stream:
        async def event_stream():
            async with http_client.stream(
                "POST", "/api/generate",
                json={"model": MODEL_NAME, "prompt": prompt, "stream": True,
                      "options": {"temperature": 0.1, "num_predict": 512, "num_ctx": 1024}},
            ) as resp:
                async for line in resp.aiter_lines():
                    data = json.loads(line)
                    yield f"data: {json.dumps({'token': data.get('response', '')})}\n\n"
                    if data.get("done"):
                        yield "data: [DONE]\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    start = time.perf_counter()
    translation = await generate(prompt)
    elapsed = (time.perf_counter() - start) * 1000

    return TranslateResponse(translation=translation, target=req.target, elapsed_ms=round(elapsed, 1))


@app.post("/translate/batch", response_model=BatchResponse)
async def translate_batch(req: BatchRequest):
    start = time.perf_counter()

    tasks = [generate(build_prompt(t, req.target, req.source)) for t in req.texts]
    results = await asyncio.gather(*tasks)

    elapsed = (time.perf_counter() - start) * 1000
    return BatchResponse(translations=list(results), target=req.target, elapsed_ms=round(elapsed, 1))


@app.get("/health")
async def health():
    try:
        resp = await http_client.get("/api/tags")
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"status": "ok", "model_loaded": MODEL_NAME in models or f"{MODEL_NAME}:latest" in models}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
