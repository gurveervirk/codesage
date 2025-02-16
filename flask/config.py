import os
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env if it exists

class Config:
    NEO4J_URI = os.environ.get("NEO4J_URI", "")  # Default if not in .env
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")  # Use a strong, random secret key.  DO NOT hardcode in production
    NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
# Create an instance of the Config class
config = Config()