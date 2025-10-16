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
    key: str = None  # The key to use in the state
    return_direct: bool = False  # Indicates if the event is manually triggered

class CodeEntitySearchEvent(Event):
    """
    Event to search for code entities in the codebase.
    
    This event is triggered to find code entities (functions, classes, methods) that are relevant to the current task.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered
    prompt: str = None  # The input prompt for the search
    root_module: str = None  # The root module to search in, required if action is CodeEntitySearchEvent
    key: str = None  # The key to use in the state

class GetEntitiesInfoEvent(Event):
    """
    Event to retrieve information about code entities.
    
    This event is triggered to initiate the code generation process by retrieving information about code entities.
    """
    pass

class ProcessFullPathsEvent(Event):
    """
    Event to process full paths of code entities.
    
    This event is triggered to process the full paths of code entities to get the correct paths.
    """
    full_paths: dict[str, list[str]]  # Dictionary of full paths for code entities

class CodeGenerationEvent(Event):
    """
    Event to generate code based on the input prompt and retrieved entities.
    
    This event is triggered to generate code based on the input prompt and the information retrieved about code entities.
    """
    return_direct: bool = False  # Indicates if the event is manually triggered

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

class RespondEvent(Event):
    """
    Event to respond to the user with the generated code or other relevant information.
    
    This event is triggered to provide a response to the user based on the generated code or other relevant information.
    """
    pass

class ReplanEvent(Event):
    """
    Event to replan the workflow based on the current state and user input.
    
    This event is triggered to re-evaluate the current state and determine the next steps in the workflow.
    """
    problem: str  # The problem to replan for