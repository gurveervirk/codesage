from flask import Flask,g
from config import config
from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from routes.upload_module import upload_module_bp
from routes.generate import generate_bp
from routes.models import models_bp
from utils.gemini_with_rate_limits import GeminiWithRateLimits as Gemini
from code_sage.com_store import COMStore
app = Flask(__name__)

app.config["NEO4J_URI"] = config.NEO4J_URI
app.config["NEO4J_USER"] = config.NEO4J_USER
app.config["NEO4J_PASSWORD"] = config.NEO4J_PASSWORD
app.config["GEMINI_API_KEY"] = config.GEMINI_API_KEY
app.register_blueprint(upload_module_bp, url_prefix='/upload-module')
app.register_blueprint(generate_bp, url_prefix='/generate')
app.register_blueprint(models_bp, url_prefix='/models')

def initialize_llamaindex():
    """Initializes LlamaIndex using the Settings object."""
    try:
        # --- LlamaIndex Initialization ---
        embed_model = HuggingFaceEmbedding(model_name = "mixedbread-ai/mxbai-embed-large-v1",
            embed_batch_size = 25)
        Settings.embed_model = embed_model
        Settings.llm = Gemini(model_name = "models/gemini-2.0-flash-001",api_key=app.config["GEMINI_API_KEY"], temperature=1, rate_limit=5, period=60)
        app.current_model="Gemini::models/gemini-2.0-flash-001"
        print("LlamaIndex settings initialized successfully using Settings object.")
        app.com_store = COMStore(username=app.config["NEO4J_USER"], password=app.config["NEO4J_PASSWORD"], url=app.config["NEO4J_URI"])

    except Exception as e:
        print(f"Error initializing LlamaIndex: {e}")
        exit(1)
        # Handle the error appropriately (e.g., log, raise, exit)

with app.app_context():
        initialize_llamaindex()

if __name__ == "__main__":
    app.run()