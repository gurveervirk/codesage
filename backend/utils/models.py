from llama_index.core.bridge.pydantic import BaseModel
from typing import Literal, Any

class Plan(BaseModel):
    """
    Represents a plan for the next steps in the workflow with the following attributes:
    
    Attributes:
        objective (str): The main objective of the plan.
        requirements (list[str]): A list of requirements that need to be fulfilled in the plan.
    """
    objective: str
    requirements: list[str]

class OrchestrationResult(BaseModel):
    """
    Represents the result of an orchestration step with the following attributes:
    
    Attributes:
        analysis (str): A analysis of the chat history to understand the context and requirements.
        action (Literal): The next action to be taken, which can be one of the following:
            - "RootModuleSearchEvent"
            - "CodeEntitySearchEvent"
            - "CodeGenerationEvent"
            - "EndEvent"
        root_module (str): The root module to search in, required if action is CodeEntitySearchEvent.
        relevant_code_entities (dict[str, str]): A dictionary of relevant code entities, required if action is CodeGenerationEvent.
        prompt (str): The input prompt for the next step, required except if action is EndEvent.
    """
    analysis: str
    action: Literal["RootModuleSearchEvent", "CodeEntitySearchEvent", "CodeGenerationEvent", "EndEvent"]
    root_module: str = None  # Required if action is CodeEntitySearchEvent
    relevant_code_entities: dict[str, str] = None  # Required if action is CodeGenerationEvent
    prompt: str = None  # Required except if action is EndEvent

class RootModuleSearchResult(BaseModel):
    """
    Represents the result of a root module search with the following attributes:
    
    Attributes:
        relevant_root_modules (list[str]): A list of relevant root modules found in the codebase, required if `end` = True.
        end (bool): Indicates if the search has ended, required if `end` = True
    """
    relevant_root_modules: list[str] = []  # List of relevant root modules in order of relevance, required if `end` = True
    end: bool = False  # Indicates if the search has ended, required if `end` = True

class CodeEntitySearchResult(BaseModel):
    """
    Represents the result of a code entity search with the following attributes:
    
    Attributes:
        relevant_code_entities (list[str]): A list of relevant code entities found in the codebase, required if `end` = True.
        end (bool): Indicates if the search has ended, required if `end` = True.
    """
    relevant_code_entities: list[str] = []  # List of relevant code entities in order of relevance, required if `end` = True
    end: bool = False  # Indicates if the search has ended, required if `end` = True

class CodeGenOrchestrationResult(BaseModel):
    """
    Represents the result of a code generation orchestration step with the following attributes:
    
    Attributes:
        analysis (str): A analysis of the chat history to understand the context and requirements.
        end (bool): Indicates if the orchestration has ended, required if `end` = True.
    """
    analysis: str
    end: bool = False  # Indicates if the orchestration has ended, required if `end` = True

class CodeGenResult(BaseModel):
    """
    Represents the result of a code generation step with the following attributes:
    
    Attributes:
        analysis (str): A analysis of the chat history to understand the context and requirements.
        code (str): The generated code that fulfills the requirements specified in the input prompt.
    """
    analysis: str
    code: str

class CodeReview(BaseModel):
    """
    Represents a code review with the following attributes:
    
    Attributes:
        review (str): The review comments or feedback on the code.
        correctness (bool): Indicates if the code is correct.
        functionality (bool): Indicates if the code functions as intended.
        best_practices (bool): Indicates if the code follows best practices.
        error_handling (bool): Indicates if the code has proper error handling.
        incorrect_usage_entities (list): A list of entities that are incorrectly used in the code, mentioned with their full names.
        missing_info_entities (list): A list of entities that are missing in the code, mentioned with their full names.
    """
    review: str
    correctness: bool
    functionality: bool
    best_practices: bool
    error_handling: bool
    incorrect_usage_entities: list[str]
    missing_info_entities: list[str]