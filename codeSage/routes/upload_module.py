from config import config
import sys
import os
from code_sage.reflex import process_module
from flask import Blueprint, request, jsonify,current_app
import subprocess


upload_module_bp = Blueprint('upload_module', __name__)

def is_module_installed(module_name):
    """Checks if a Python module is installed."""
    try:
        __import__(module_name)  # Try to import the module
        return True  # If import succeeds, the module is installed
    except ImportError:
        return False  # If import fails, the module is not installed


def install_module(module_name):
    """Installs a Python module using pip."""
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', module_name])
        return True  # Installation succeeded
    except subprocess.CalledProcessError as e:
        print(f"Error installing module {module_name}: {e}")
        return False 

@upload_module_bp.route('/', methods=['POST'])
def upload_module():
    try:
        data = request.get_json()
        if not data or 'module_name' not in data:
            return jsonify({'error': 'Module name is required in the request body'}), 400
        module_name = data['module_name']
        if not is_module_installed(module_name):
            # Install the module if it's not installed
            if not install_module(module_name):
                return jsonify({'error': f'Failed to install module: {module_name}'}), 500
            else:
                print(f"Module {module_name} installed successfully.")
        entities,relations,other_relations = process_module(module_name)
        current_app.com_store.upsert_to_neo4j(module_name=module_name,entities=entities,relations=relations,other_relations=other_relations)
        return jsonify({'message': 'Module uploaded successfully'}), 200
    except Exception as e:
        print(e.with_traceback())
        return jsonify({'error': f'Failed to upload module: {e}'}), 500

    

