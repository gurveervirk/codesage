from fastapi import FastAPI
from config import config
from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from routes.upload_module import upload_module_router
from routes.generate import generate_router
from routes.llm_models import llm_models_router
from backend.code_sage.sage_workflow.mas import SageWorkflow
# from utils.gemini_with_rate_limits import GeminiWithRateLimits as Gemini
from llama_index.llms.google_genai import GoogleGenAI
from backend.code_sage.com_store import COMStore

app = FastAPI(
    title="CodeSage API",
    description="API for using CodeSage, a smarter code assistant.",
    version="1.0.0"
)

@app.on_event("startup")
async def initialize_llamaindex():
    """Initializes LlamaIndex and application state on startup."""
    try:
        # Initialize embedding model
        embed_model = HuggingFaceEmbedding(
            model_name="mixedbread-ai/mxbai-embed-large-v1",
            embed_batch_size=25
        )
        Settings.embed_model = embed_model
        # Initialize LLM
        Settings.llm = GoogleGenAI(
            api_key=config.GEMINI_API_KEY,
            temperature=1.0,
            # rate_limit=15,
            # period=60
        )
        # Store model and services in app state
        app.state.current_model = "Gemini::" + Settings.llm.model
        app.state.com_store = COMStore(
            username=config.NEO4J_USER,
            password=config.NEO4J_PASSWORD,
            url=config.NEO4J_URI
        )
        app.state.workflow = SageWorkflow(com_store=app.state.com_store)
    except Exception as e:
        print(f"Error initializing LlamaIndex: {e}")
        raise

# Include routers
app.include_router(upload_module_router, prefix="/upload-module", tags=["Upload Module"])
app.include_router(generate_router, prefix="/generate", tags=["Generate"])
app.include_router(llm_models_router, prefix="/models", tags=["Models"])