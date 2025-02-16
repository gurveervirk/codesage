from flask import Flask
from config import config
from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from routes.upload_module import upload_module_bp
from routes.generate import generate_bp
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),  '..','..'))
sys.path.insert(0, project_root)

from gemini_with_rate_limits import GeminiWithRateLimits as Gemini
app = Flask(__name__)

app.config["NEO4J_URI"] = config.NEO4J_URI
app.config["NEO4J_USER"] = config.NEO4J_USER
app.config["NEO4J_PASSWORD"] = config.NEO4J_PASSWORD
app.config["GEMINI_API_KEY"] = config.GEMINI_API_KEY

app.register_blueprint(upload_module_bp, url_prefix='/upload-module')
app.register_blueprint(generate_bp, url_prefix='/generate')

def initialize_llamaindex():
    """Initializes LlamaIndex using the Settings object."""
    try:
        # --- LlamaIndex Initialization ---
        embed_model = HuggingFaceEmbedding(model_name = "mixedbread-ai/mxbai-embed-large-v1",
            embed_batch_size = 25)
        Settings.embed_model = embed_model
        Settings.llm = Gemini(api_key=app.config["GEMINI_API_KEY"], temperature=1, rate_limit=5, period=60)
        print("LlamaIndex settings initialized successfully using Settings object.")

    except Exception as e:
        print(f"Error initializing LlamaIndex: {e}")
        exit(1)
        # Handle the error appropriately (e.g., log, raise, exit)

with app.app_context():
        initialize_llamaindex()

if __name__ == "__main__":
    app.run()