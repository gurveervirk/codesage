from config import config
from flask import Blueprint, request, jsonify,current_app
from config import config
from llama_index.core.settings import Settings
import sys
import os
# from llama_index.llms.ollama import Ollama
# from llama_index.llms.openai import OpenAI
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),  '..','..'))
sys.path.insert(0, project_root)

from gemini_with_rate_limits import GeminiWithRateLimits as Gemini
models_bp = Blueprint('models', __name__)

@models_bp.route('/get-models', methods=['GET'])
def available_models():
    """Returns a list of available models."""
    try:
        # Get the list of available models from the config file
        models = config.AVAILABLE_MODELS
        
        models["Current-Model"] = [{"id":current_app.current_model,"name":""}]
        return jsonify(models), 200
    except Exception as e:
        print(e)
        return jsonify({'error': f'Failed to get models: {e}'}), 500
@models_bp.route('/change-model', methods=['POST'])
def change_models():
    """Changes the currently selected model."""
    try:
        # Get the provider and id from the request
        provider = request.json.get('provider')
        id = request.json.get('id')
        if provider=="Gemini":
            Settings.llm = Gemini(model_name=id,api_key=config.GEMINI_API_KEY, temperature=1, rate_limit=5, period=60)
            current_app.current_model = "Gemini:"+id
        elif provider=="Ollama":
            # Settings.llm = Ollama(model=id, request_timeout=120.0, base_url="http://localhost:11434")
            # g.current_model = "Ollama:"+id
            pass
        elif provider=="OpenAI":
            # Settings.llm = OpenAI(model=id, api_key=config.OPENAI_API_KEY, temperature=1)
            # g.current_model = "OpenAI:"+id
            pass
        return jsonify({'message': 'Changed model successfully'}), 200
    except Exception as e:
        print("Failed"+e)
        return jsonify({'error': f'Failed to change model: {e}'}), 500