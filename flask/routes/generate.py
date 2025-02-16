from config import config
import sys
import os
from flask import Blueprint, request, jsonify
import asyncio
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),  '..','..'))
sys.path.insert(0, project_root)

from com_store import COMStore

generate_bp = Blueprint('generate', __name__)

@generate_bp.route('/generate-example', methods=['POST'])
def generate():
    data = request.get_json()
    if not data or 'entity_name' not in data:
        return jsonify({'error': 'No data provided'}), 400
    entity_name = data['entity_name']
    com_store = COMStore(username = config.NEO4J_USER,
            password = config.NEO4J_PASSWORD,
            url = config.NEO4J_URI)
    code_generated = asyncio.run(com_store.generate_code(name=entity_name))
    return jsonify({'message': 'Code generated successfully',
                    'example_code': str(code_generated) }), 200
    
