from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio

app = FastAPI(title="TrackMyTrain Master API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global memory caches for Vercel edge
STATIONS_CACHE = []
TRAINS_CACHE = []
TARGET_API = "https://whereismytrain.org.in/api"
PNR_API = "https://railsinfo-services.makemytrip.com/api/rails/pnr/currentstatus/v1"

# Stealth headers for WhereIsMyTrain
STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://whereismytrain.org.in/"
}

# Stealth headers for MakeMyTrip
MMT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.makemytrip.com",
    "Referer": "https://www.makemytrip.com/"
}

async def fetch_data_from_r2():
    """Concurrently fetches both master databases on cold start."""
    global STATIONS_CACHE, TRAINS_CACHE
    
    async with httpx.AsyncClient() as client:
        if not STATIONS_CACHE:
            try:
                res_st = await client.get("https://cdn.bittu.me/TrackMyTrain/stations.json", timeout=10.0)
                if res_st.status_code == 200:
                    STATIONS_CACHE = res_st.json().get("data", [])
            except Exception as e:
                print(f"Stations Fetch Error: {e}")
                STATIONS_CACHE = []
                
        if not TRAINS_CACHE:
            try:
                res_tr = await client.get("https://cdn.bittu.me/TrackMyTrain/trains.json", timeout=10.0)
                if res_tr.status_code == 200:
                    TRAINS_CACHE = res_tr.json().get("data", [])
            except Exception as e:
                print(f"Trains Fetch Error: {e}")
                TRAINS_CACHE = []


@app.get("/")
@app.head("/")
async def root():
    """Health check endpoint strictly for keep-alive pings."""
    return {
        "success": True,
        "message": "TrackMyTrain API is live 🚂",
        "developer": "BITTU_DEV",
        "status": "online",
        "endpoints": {
            "search": "/api/search?type={type}&q={query}&limit={limit}",
            "route": "/api/trains/between-stations?from={code}&to={code}",
            "live_status": "/api/trains/live-status?trainNo={number}",
            "pnr_status": "/api/pnr-status?pnr={pnr_number}"
        }
    }


@app.get("/api/search")
async def search(type: str = "station", q: str = "", limit: int = 8):
    """Zero-latency autocomplete routing between the two offline datasets."""
    await fetch_data_from_r2()
    
    clean_q = q.lower().strip()
    results = []
    
    if not clean_q:
        return {"success": True, "data": results, "total": 0, "query": q, "type": type}

    if type == "station":
        if "(" in clean_q and ")" in clean_q:
            start = clean_q.find("(") + 1
            end = clean_q.find(")")
            clean_q = clean_q[start:end].strip()

        for st in STATIONS_CACHE:
            if clean_q in str(st.get("code", "")).lower() or clean_q in str(st.get("name", "")).lower():
                results.append(st)
                if len(results) >= limit:
                    break

    elif type == "train":
        for tr in TRAINS_CACHE:
            if clean_q in str(tr.get("number", "")).lower() or clean_q in str(tr.get("name", "")).lower():
                results.append(tr)
                if len(results) >= limit:
                    break

    return {
        "success": True, 
        "data": results, 
        "total": len(results), 
        "query": q,
        "type": type
    }


@app.get("/api/trains/between-stations")
async def between_stations(from_station: str = Query(..., alias="from"), to_station: str = Query(..., alias="to")):
    async with httpx.AsyncClient() as client:
        try:
            url = f"{TARGET_API}/trains/between-stations?from={from_station}&to={to_station}"
            response = await client.get(url, headers=STEALTH_HEADERS, timeout=15.0)
            return response.json()
        except httpx.TimeoutException:
            return JSONResponse(status_code=504, content={"success": False, "message": "Upstream API timeout"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": f"Proxy error: {str(e)}"})


@app.get("/api/trains/live-status")
async def live_status(trainNo: str):
    async with httpx.AsyncClient() as client:
        try:
            url = f"{TARGET_API}/trains/live-status?trainNo={trainNo}"
            response = await client.get(url, headers=STEALTH_HEADERS, timeout=15.0)
            return response.json()
        except httpx.TimeoutException:
            return JSONResponse(status_code=504, content={"success": False, "message": "Upstream API timeout"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": f"Proxy error: {str(e)}"})


@app.get("/api/pnr-status")
async def get_pnr_status(pnr: str):
    """Translates a simple GET request into MMT's required POST payload."""
    # Basic validation to ensure the PNR is 10 digits
    if not pnr.isdigit() or len(pnr) != 10:
        return JSONResponse(status_code=400, content={"success": False, "message": "Invalid PNR Number. Must be 10 digits."})

    payload = {
        "pnrID": pnr,
        "trackingParams": {
            "affiliateCode": "MMT001",
            "channelCode": "PWA"
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            # We send a POST request, but your bot only needs to send a GET request!
            response = await client.post(PNR_API, json=payload, headers=MMT_HEADERS, timeout=15.0)
            
            # Wrap MMT's response inside our standard success format
            return {
                "success": True,
                "data": response.json()
            }
        except httpx.TimeoutException:
            return JSONResponse(status_code=504, content={"success": False, "message": "MakeMyTrip API timeout"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": f"Proxy error: {str(e)}"})
