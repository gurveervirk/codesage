from llama_index.core.workflow import Event
from typing import Any

class OrchestrationEvent(Event):
    """
    Event to orchestrate the workflow based on the input prompt and chat history.
    
    This event is triggered to analyze the chat history and determine the next step in the workflow.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    result_keys: dict[str, Any] = None  # Optional keys to be used in the orchestration result

class RootModuleSearchEvent(Event):
    """
    Event to search for root modules in the codebase.
    
    This event is triggered to find the root modules that are relevant to the current task.
    """
    prompt: str = None  # The input prompt for the search
    return_direct: bool = False  # Indicates if the event is manually triggered

class CodeEntitySearchEvent(Event):
    """
    Event to search for code entities in the codebase.
    
    This event is triggered to find code entities (functions, classes, methods) that are relevant to the current task.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    prompt: str = None  # The input prompt for the search
    root_module: str = None  # The root module to search in, required if action is CodeEntitySearchEvent

class CodeGenerationEvent(Event):
    """
    Event to orchestrate code generation based on the input prompt and relevant code entities.
    
    This event is triggered to generate code that fulfills the requirements specified in the input prompt.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    prompt: str
    relevant_code_entities: list[str]
    success: bool = False  # Indicates if the code generation was successful

class GenerateCodeEvent(Event):
    """
    Event to generate code based on the input prompt and relevant code entities.
    
    This event is triggered to generate code that fulfills the requirements specified in the input prompt.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    prompt: str
    relevant_code_entities: list[str]
    additional_instructions: str = None  # Optional additional instructions for code generation

class ReviewEvent(Event):
    """
    Event to review the generated code.
    
    This event is triggered to review the results generated against the input prompt.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    input: str
    result: str

class EntitiesEvent(Event):
    """
    Event that returns information about multiple code entities.
    
    This event is triggered to retrieve information about multiple code entities, such as their definitions, usages, and related entities.
    """
    entities: list[dict[str, Any]]  # List of entities to retrieve information about