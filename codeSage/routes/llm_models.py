from config import config
from fastapi import APIRouter, HTTPException, Request
from .models import ChangeModelRequest
from llama_index.core.settings import Settings
from llama_index.llms.ollama import Ollama
from llama_index.llms.google_genai import GoogleGenAI

# from utils.gemini_with_rate_limits import GeminiWithRateLimits as Gemini

llm_models_router = APIRouter()

@llm_models_router.get(
    "/get-models",
    response_model=dict,
    summary="Retrieve available and current models"
)
async def available_models(request: Request):
    """
    Returns a list of configured LLM providers and the currently selected model.
    """
    try:
        models = config.AVAILABLE_MODELS.copy()
        models["Current-Model"] = [{"id": request.app.state.current_model, "name": ""}]
        return models
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@llm_models_router.post(
    "/change-model",
    response_model=dict,
    summary="Change the active LLM model and provider"
)
async def change_models(request: Request, payload: ChangeModelRequest):
    """
    Alters the active LLM based on provider ('Gemini', 'Ollama', or 'OpenAI') and model ID.
    """
    try:
        provider = payload.provider
        model_id = payload.id
        if provider == "Gemini":
            Settings.llm = GoogleGenAI(
                api_key=config.GEMINI_API_KEY,
                temperature=1.0,
                # rate_limit=15,
                # period=60,
                model=model_id
            )
            request.app.state.current_model = f"Gemini::{model_id}"
        elif provider == "Ollama":
            Settings.llm = Ollama(
                model=model_id,
                request_timeout=120.0,
                base_url="http://localhost:11434"
            )
            request.app.state.current_model = f"Ollama::{model_id}"
        elif provider == "OpenAI":
            # Uncomment and configure OpenAI when available
            # Settings.llm = OpenAI(model=model_id, api_key=config.OPENAI_API_KEY, temperature=1)
            request.app.state.current_model = f"OpenAI::{model_id}"
        else:
            raise HTTPException(status_code=400, detail="Unsupported provider")
        return {"message": "Changed model successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))