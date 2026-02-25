import os
from dotenv import load_dotenv

BASEDIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASEDIR, ".env"))

class Config:
    NEO4J_URI = os.environ.get("NEO4J_URI", "")  # Default if not in .env
    GOOGLE_GENAI_API_KEY = os.environ.get("GOOGLE_GENAI_API_KEY", "")
    NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")  # Use a strong, random secret key.  DO NOT hardcode in production
    NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
    SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL") or os.environ.get("POSTGRES_URL", "")
    AVAILABLE_MODELS = {
    "Gemini":[{"id": "gemini-2.0-flash", "name": "Flash 2.0"},{ "id": "gemini-1.5-pro", "name": "Flash 1.5 pro"}],
    "Ollama":[{"id": "mistral:latest", "name": "Mistral"}],
    }
    
# Create an instance of the Config class
config = Config()