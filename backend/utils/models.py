from llama_index.core.bridge.pydantic import BaseModel, create_model
from typing import Literal
from pydantic import Field
from pydantic_core import PydanticUndefined

class Requirement(BaseModel):
    """
    Represents a requirement for the next steps in the workflow with the following attributes:
    
    Attributes:
        key (str): Unique identifier for the requirement.
        requirement_type (Literal): The type of the requirement, which can be one of the following:
            - "RMS" (Root Module Search)
            - "CES" (Code Entity Search)
            - "CG" (Code Generation)
        query (str): The query or prompt for the requirement.
        dependency (str): The key of the requirement that this requirement depends on, if any.
    """
    key: str = None  # Unique identifier for the requirement
    requirement_type: Literal["RMS", "CES", "CG"] = None
    query: str = None
    dependency: str = None  # Key of the requirement that this requirement depends on, if any

class Plan(BaseModel):
    """
    Represents a plan for the next steps in the workflow with the following attributes:
    
    Attributes:
        objective (str): The main objective of the plan.
        requirements (list[Requirement]): A list of requirements for the next steps in the workflow.
    """
    objective: str = None
    requirements: list[Requirement] = None  # A list of requirements for the next steps in the workflow

class ReplanResult(BaseModel):
    """
    Represents the result of a replan step with the following attributes:
    
    Attributes:
        analysis (str): A analysis of the chat history to understand the context and requirements.
        keys_to_remove (list[str]): A list of keys to remove from the plan.
        new_requirements (list[Requirement]): A list of new requirements to add to the plan.
    """
    analysis: str = None  # A analysis of the chat history to understand the context and requirements
    keys_to_remove: list[str] = None  # A list of keys to remove from the plan
    new_requirements: list[Requirement] = None  # A list of new requirements to add to the plan

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
        most_relevant_root_module (str): The most relevant root module found, required if `end` = True.
    """
    most_relevant_root_module: str = None  # The most relevant root module found, required

class CodeEntitySearchResult(BaseModel):
    """
    Represents the result of a code entity search with the following attributes:
    
    Attributes:
        most_relevant_code_entity (str): The most relevant code entity found, required if `end` = True.
    """
    most_relevant_code_entity: str = None  # The most relevant code entity found, required

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

class PathMapping(BaseModel):
    """
    Maps incorrect paths to correct paths for code entities.

    Attributes:
        path_mapping (list[dict[str, str]]): A list of dictionaries where each dictionary maps an incorrect path to a correct path.
    """
    path_mapping: list[dict[str, str]] = None  # A list of dictionaries mapping incorrect paths to correct paths

class EndArgs(BaseModel):
    """
    Represents the arguments for the end of a workflow with the following attributes:
    
    Attributes:
        end (bool): Indicates if the workflow has ended.
        end_type (Literal): The type of end, can be "success" or "failure".
        reason (str): The reason for the end, if any.
    """
    end: bool = False
    end_type: Literal["success", "failure"] = None  # Type of end, can be "success" or "failure"
    reason: str = None  # Reason for the end, if any

class Utility(BaseModel):
    """
    Represents a utility model that can be used to add additional fields to the main model.
    
    This model can be extended with additional fields as needed.
    """
    end_args: EndArgs = None  # Arguments for the end of a workflow

def create_output_model(main_model: BaseModel) -> BaseModel:
    """
    Dynamically creates a Pydantic model that includes:
    1. All fields from the provided main_model directly.
    2. All fields from the Utility model directly.
    
    Args:
        main_model (BaseModel): The main Pydantic model whose fields will be included.
        
    Returns:
        BaseModel: A new Pydantic model combining fields from main_model and Utility.
    """
    model_name = f"Extended{main_model.__name__}"
    
    # Prepare Utility's fields in the format required by create_model
    additional_fields_from_utility: dict = {}
    for field_name, field_info in Utility.model_fields.items():
        # Determine the default value or if it's required
        if field_info.default is PydanticUndefined:
            # Field is required
            additional_fields_from_utility[field_name] = (field_info.annotation, ...)
        elif field_info.default_factory is not None:
            # Field has a default factory
            additional_fields_from_utility[field_name] = (field_info.annotation, Field(default_factory=field_info.default_factory))
        else:
            # Field has a default value (which could be None)
            additional_fields_from_utility[field_name] = (field_info.annotation, field_info.default)

    # Create the new model dynamically
    ExtendedModel = create_model(
        model_name,
        __base__=main_model,  # Inherit all fields and validators from main_model
        **additional_fields_from_utility, # Add the fields from Utility
        # You generally don't need `arbitrary_types_allowed=True` if all your fields
        # are Pydantic models or standard Python types.
        # However, if EndArgs wasn't a BaseModel, you might need it.
        # Keeping for demonstration:
        # __config__=type('Config', (), {'arbitrary_types_allowed': True})
    )

    return ExtendedModel