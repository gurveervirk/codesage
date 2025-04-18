from pydantic import BaseModel

class ChangeModelRequest(BaseModel):
    """
    Request model for changing the current LLM provider and model ID.
    """
    provider: str
    id: str

class ModuleUploadRequest(BaseModel):
    """
    Request model for uploading a Python module.
    """
    module_name: str


class ChatRequest(BaseModel):
    """
    Request model for chat workflow.
    """
    prompt: str

class ContextRequest(BaseModel):
    """
    Request model for context operations.
    """
    id: str