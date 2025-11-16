import os
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from database import db, create_document, get_documents

app = FastAPI(title="ChromaPrint API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Models (request bodies)
# -----------------------------
class LoginRequest(BaseModel):
    email: str
    password: str

class EstimateRequest(BaseModel):
    length_mm: float = Field(..., gt=0)
    width_mm: float = Field(..., gt=0)
    height_mm: float = Field(..., gt=0)
    material: str = Field(..., description="PLA | ABS | Resin | Nylon | PETG")
    finish: str = Field(..., description="Standard | Smooth | High-Gloss | Matte")
    complexity: float = Field(1.0, ge=0.5, le=2.0, description="Complexity multiplier")
    infill: float = Field(0.2, ge=0.05, le=1.0, description="0-1 infill density")
    model_volume_mm3: Optional[float] = Field(None, ge=0)

class QuoteRequest(BaseModel):
    email: str
    name: Optional[str] = None
    estimate: Dict[str, Any]
    notes: Optional[str] = None

# -----------------------------
# Utilities and seed data
# -----------------------------
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "ankitmht42@gmail.com")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Ankitmehta007")
DEMO_TOKEN = "demo-token-123"

PRINTER_COLLECTION = "printer"
QUOTE_COLLECTION = "quote"

SAMPLE_PRINTERS = [
    {
        "title": "ChromaPrint Pro X1",
        "brand": "ChromaPrint",
        "price_inr": 149999,
        "image": "https://images.unsplash.com/photo-1581091012184-7c54c7d64c9b?q=80&w=1200&auto=format&fit=crop",
        "features": ["Skin-tone accurate calibration", "300mm³ build volume", "Dual extruder", "Silent core"] ,
        "specs": {"build_volume_mm": "300 x 300 x 300", "layer_height": "50-300μm", "nozzle": "0.4mm"}
    },
    {
        "title": "ChromaPrint Studio S2",
        "brand": "ChromaPrint",
        "price_inr": 89999,
        "image": "https://images.unsplash.com/photo-1581090485640-7f4c1e5c127c?q=80&w=1200&auto=format&fit=crop",
        "features": ["AI color profiling", "Auto-leveling", "Wi‑Fi"],
        "specs": {"build_volume_mm": "220 x 220 x 250", "layer_height": "100-300μm", "nozzle": "0.4mm"}
    },
    {
        "title": "ChromaPrint Resin R1",
        "brand": "ChromaPrint",
        "price_inr": 129999,
        "image": "https://images.unsplash.com/photo-1581090700227-1e37b32f0d06?q=80&w=1200&auto=format&fit=crop",
        "features": ["Ultra-fine detail", "Dermatone matching", "Enclosed chamber"],
        "specs": {"build_volume_mm": "130 x 80 x 160", "layer_height": "25-100μm"}
    }
]

MATERIAL_RATE_PER_CM3_INR = {
    "PLA": 4.0,
    "ABS": 5.0,
    "Resin": 12.0,
    "Nylon": 9.0,
    "PETG": 6.0,
}

FINISH_MULTIPLIER = {
    "Standard": 1.0,
    "Smooth": 1.15,
    "High-Gloss": 1.3,
    "Matte": 1.1,
}

# -----------------------------
# Basic endpoints
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "ChromaPrint Backend is live"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from ChromaPrint API"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# -----------------------------
# Auth (demo)
# -----------------------------
@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.email == DEMO_EMAIL and req.password == DEMO_PASSWORD:
        # Optionally seed a demo user record
        try:
            if db is not None:
                db["user"].update_one(
                    {"email": DEMO_EMAIL},
                    {"$setOnInsert": {"name": "Demo User", "email": DEMO_EMAIL, "created_at": datetime.utcnow()}},
                    upsert=True,
                )
        except Exception:
            pass
        return {"token": DEMO_TOKEN, "user": {"email": DEMO_EMAIL, "name": "Demo User"}}
    raise HTTPException(status_code=401, detail="Invalid credentials. Use demo credentials provided.")

# -----------------------------
# Printers (seed + list)
# -----------------------------
@app.get("/api/printers")
def list_printers():
    if db is None:
        # Fallback to in-memory results if db not available
        return {"items": SAMPLE_PRINTERS}
    # Seed if empty
    if db[PRINTER_COLLECTION].count_documents({}) == 0:
        try:
            db[PRINTER_COLLECTION].insert_many([{**p, "created_at": datetime.utcnow()} for p in SAMPLE_PRINTERS])
        except Exception:
            pass
    items = list(db[PRINTER_COLLECTION].find({}, {"_id": 0}))
    return {"items": items}

# -----------------------------
# AI Cost Estimator (mock)
# -----------------------------
@app.post("/api/estimate")
def estimate_cost(req: EstimateRequest):
    # Derive volume (mm^3). If model provided, use it; else approximate bounding box * infill factor.
    if req.model_volume_mm3 is not None and req.model_volume_mm3 > 0:
        volume_mm3 = req.model_volume_mm3 * max(0.05, min(1.0, req.infill))
    else:
        bbox_mm3 = req.length_mm * req.width_mm * req.height_mm
        # shell + infill approximation
        volume_mm3 = bbox_mm3 * (0.02 + 0.78 * req.infill)

    volume_cm3 = volume_mm3 / 1000.0  # 1 cm3 = 1000 mm3

    material_rate = MATERIAL_RATE_PER_CM3_INR.get(req.material, 5.0)
    finish_mult = FINISH_MULTIPLIER.get(req.finish, 1.0)

    base_cost = volume_cm3 * material_rate
    machine_time_hours = max(0.5, volume_cm3 / 8.0)  # heuristic
    machine_cost = machine_time_hours * 120.0  # INR per hour
    handling = 80.0
    color_match = 60.0  # for skin-tone profiling

    subtotal = (base_cost + machine_cost + handling + color_match) * req.complexity
    estimated_cost = max(150.0, subtotal * finish_mult)

    breakdown = {
        "volume_cm3": round(volume_cm3, 2),
        "material_rate_inr_per_cm3": material_rate,
        "machine_time_hours": round(machine_time_hours, 2),
        "finish_multiplier": finish_mult,
        "complexity": req.complexity,
        "line_items": {
            "material": round(base_cost, 2),
            "machine": round(machine_cost, 2),
            "handling": handling,
            "skin_tone_color_match": color_match,
        },
    }

    return {"currency": "INR", "estimated_cost": round(estimated_cost, 2), "breakdown": breakdown}

# -----------------------------
# Quote submission
# -----------------------------
@app.post("/api/quote")
def submit_quote(body: QuoteRequest, x_demo_token: Optional[str] = Header(default=None)):
    if x_demo_token != DEMO_TOKEN:
        raise HTTPException(status_code=401, detail="Authentication required. Please login with demo credentials.")

    data = {
        "email": body.email,
        "name": body.name,
        "estimate": body.estimate,
        "notes": body.notes,
        "status": "submitted",
        "created_at": datetime.utcnow(),
    }

    if db is None:
        # Simulate success without persistence
        return {"ok": True, "message": "Quote submitted. Final price will be emailed (simulated)."}

    quote_id = create_document(QUOTE_COLLECTION, data)
    return {"ok": True, "id": quote_id, "message": "Quote submitted. Final price will be emailed (simulated)."}

# -----------------------------
# Account - orders/quotes list
# -----------------------------
@app.get("/api/account/orders")
def list_orders(email: str):
    if db is None:
        return {"items": []}
    docs = get_documents(QUOTE_COLLECTION, {"email": email}, limit=50)
    # Convert ObjectId to string for _id if present
    items = []
    for d in docs:
        d_copy = {k: v for k, v in d.items() if k != "_id"}
        if "_id" in d:
            d_copy["id"] = str(d["_id"])
        items.append(d_copy)
    return {"items": items}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
