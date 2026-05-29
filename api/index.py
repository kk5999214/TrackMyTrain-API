from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="TrackMyTrain Master API")

# Allow your frontend/bot to access the API without CORS errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global memory cache for Vercel serverless instances
STATIONS_CACHE = []
TARGET_API = "https://whereismytrain.org.in/api"

# Stealth headers to avoid target API WAF blocks
STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://whereismytrain.org.in/"
}

async def fetch_stations_from_r2():
    """Fetches the master DB from your Cloudflare R2 bucket on cold start."""
    global STATIONS_CACHE
    if not STATIONS_CACHE:
        async with httpx.AsyncClient() as client:
            try:
                # Using your R2 CDN
                response = await client.get("https://cdn.bittu.me/TrackMyTrain/stations.json", timeout=10.0)
                if response.status_code == 200:
                    STATIONS_CACHE = response.json().get("data", [])
            except Exception as e:
                print(f"R2 Fetch Error: {e}")
                # Fallback to empty to prevent hard crash
                STATIONS_CACHE = []


@app.get("/")
async def root():
    """Health check endpoint returning a structured JSON response."""
    return {
        "success": True,
        "message": "TrackMyTrain API is live 🚂",
        "developer": "BITTU_DEV",
        "status": "online",
        "endpoints": {
            "search": "/api/search?q={query}",
            "route": "/api/trains/between-stations?from={code}&to={code}",
            "live_status": "/api/trains/live-status?trainNo={number}"
        }
    }


@app.get("/api/search")
async def search_stations(q: str = "", type: str = "station", limit: int = 8):
    """Zero-latency autocomplete using R2 memory cache and fixing the formatting bug."""
    await fetch_stations_from_r2()
    
    clean_q = q.lower().strip()
    
    # Bug Fix: If frontend sends "Howrah Jn (HWH)", extract just "hwh"
    if "(" in clean_q and ")" in clean_q:
        start = clean_q.find("(") + 1
        end = clean_q.find(")")
        clean_q = clean_q[start:end].strip()

    results = []
    if clean_q:
        for st in STATIONS_CACHE:
            # Fast substring search
            if clean_q in st.get("code", "").lower() or clean_q in st.get("name", "").lower():
                results.append(st)
                if len(results) >= limit:
                    break

    return {"success": True, "data": results, "total": len(results), "query": q}


@app.get("/api/trains/between-stations")
async def between_stations(from_station: str = Query(..., alias="from"), to_station: str = Query(..., alias="to")):
    """Async proxy for station routing."""
    async with httpx.AsyncClient() as client:
        try:
            url = f"{TARGET_API}/trains/between-stations?from={from_station}&to={to_station}"
            response = await client.get(url, headers=STEALTH_HEADERS, timeout=15.0)
            
            # Pass the JSON directly back
            return response.json()
        except httpx.TimeoutException:
            return JSONResponse(status_code=504, content={"success": False, "message": "Upstream API timeout"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": f"Proxy error: {str(e)}"})


@app.get("/api/trains/live-status")
async def live_status(trainNo: str):
    """Async proxy for live tracking."""
    async with httpx.AsyncClient() as client:
        try:
            url = f"{TARGET_API}/trains/live-status?trainNo={trainNo}"
            response = await client.get(url, headers=STEALTH_HEADERS, timeout=15.0)
            
            return response.json()
        except httpx.TimeoutException:
            return JSONResponse(status_code=504, content={"success": False, "message": "Upstream API timeout"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": f"Proxy error: {str(e)}"})
