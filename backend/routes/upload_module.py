from backend.code_sage.reflex import process_module
from fastapi import APIRouter, Request, HTTPException
from backend.routes.models import ModuleUploadRequest
import subprocess
import sys

upload_module_router = APIRouter()

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

@upload_module_router.post(
    "/",
    summary="Upload and process a Python module",
    response_model=dict
)
async def upload_module(payload: ModuleUploadRequest, request: Request):
    """
    Installs a Python module (if not already installed), processes it to extract entities and relations,
    and stores the information in a Neo4j graph via the application's COMStore.
    """
    module_name = payload.module_name
    # Install module if missing
    if not is_module_installed(module_name):
        success = install_module(module_name)
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to install module: {module_name}")
    try:
        entities, relations, other_relations = process_module(module_name)
        request.app.state.com_store.upsert_to_neo4j(
            module_name=module_name,
            entities=entities,
            relations=relations,
            other_relations=other_relations
        )
        return {"message": "Module uploaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



