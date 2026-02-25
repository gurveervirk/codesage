from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import config
from backend.routes.explorer import explorer_router
from backend.core.com_store.postgres import PostgresCOMStore, PostgresCOMStoreTools

app = FastAPI(
    title="deputy API",
    description="API for using deputy, a smarter code assistant.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def init():
    """Initializes the COM store and tools on application startup."""
    try:
        pg_store = PostgresCOMStore(connection_string=config.SUPABASE_DB_URL)
        app.state.pg_tools = PostgresCOMStoreTools(pg_store)
    except Exception as e:
        print(f"Error initializing: {e}")
        raise

# Include routers
app.include_router(explorer_router, prefix="/explorer", tags=["Explorer"])