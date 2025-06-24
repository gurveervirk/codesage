from llama_index.core.workflow import (
    Workflow,
    StartEvent,
    StopEvent,
    Context,
    step,
)
from llama_index.core.workflow.handler import WorkflowHandler
from llama_index.core.agent.workflow import (
    FunctionAgent,
    AgentInput,
    AgentOutput,
    ToolCallResult,
    ToolCall,
)
from llama_index.core.tools import FunctionTool
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import PromptTemplate
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core.memory import (
    Memory,
    StaticMemoryBlock,
)
from llama_index.core import Settings
from backend.code_sage.sage_workflow.events import (
    OrchestrationEvent,
    RootModuleSearchEvent,
    CodeEntitySearchEvent,
    CodeGenerationEvent,
    GenerateCodeEvent,
    ReviewEvent,
    EntitiesEvent
)
from backend.utils.wkflw_prompts import (
    PLAN_PROMPT,
    ORCHESTRATE_PROMPT,
    ROOT_MODULE_SEARCH_PROMPT,
    CODE_ENTITY_SEARCH_PROMPT,
    CODE_GENERATION_PROMPT,
    REVIEW_PROMPT,
    STRUCTURIZE_RESPONSE_PROMPT,
)
from backend.code_sage.com_store import (
    COMStore
)
from backend.utils.models import (
    Plan,
    OrchestrationResult,
    RootModuleSearchResult,
    CodeEntitySearchResult,
    CodeGenOrchestrationResult,
    CodeGenResult
)
from backend.config import config
from typing import Any
import google.genai.types as types
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the LLM's
default_model_name = "gemini-2.0-flash"  # Default model name
default_model_temperature = 0.2  # Default temperature for the LLM

lite_model_name = "gemini-2.0-flash-lite"  # Lite model name for faster responses
lite_model_temperature = 0.2  # Temperature for the lite model

advanced_model_name = "gemini-2.5-flash"  # Advanced model name for more complex tasks
advanced_model_temperature = 0.2  # Temperature for the advanced model

DEFAULT_LLM: LLM = GoogleGenAI(
    model=default_model_name,
    temperature=default_model_temperature,
    api_key=config.GEMINI_API_KEY,
)

LITE_LLM: LLM = GoogleGenAI(
    model=lite_model_name,
    temperature=lite_model_temperature,
    api_key=config.GEMINI_API_KEY,
)

ADVANCED_LLM: LLM = GoogleGenAI(
    model=advanced_model_name,
    temperature=advanced_model_temperature,
    api_key=config.GEMINI_API_KEY,
)

# TODO: Check embedding model in future, defining a default for now
embed_model = HuggingFaceEmbedding(
    model_name="mixedbread-ai/mxbai-embed-large-v1",
    embed_batch_size=25
)
Settings.embed_model = embed_model

class MainWkflw(Workflow):
    """
    A workflow for:
    - Fetching relevant code entities for requested functionalities
    - Generating code based on these entities
    - Reviewing the generated code for correctness, functionality, and best practices
    """
    com_store: COMStore = None
    tools: dict[str, list[FunctionTool]] = None

    # Create functions that handle async event management
    async def retrieve_relevant_root_modules(self, ctx: Context, query: str, top_k: int) -> dict[str, Any]:
        """
        Retrieve all relevant root modules based on the query, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: Top k Relevant root modules based on the query formatted as a string.
        """
        results = self.com_store.retrieve_relevant_root_modules(
            query=query,
            top_k=top_k
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def retrieve_relevant_children_in_subtree(self, ctx: Context, query: str, parent_name: str, top_k: int) -> dict[str, Any]:
        """
        Retrieve all relevant children in the subtree based on the query and parent name, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            parent_name (str): The name of the parent module.
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: Top k Relevant children in the subtree based on the query formatted as a string.
        """
        results = self.com_store.retrieve_relevant_children_in_subtree(
            query=query,
            parent_name=parent_name,
            top_k=top_k
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def next_top_k_root_modules(self, ctx: Context, top_k: int) -> str:
        """
        Retrieve the next set of top k root modules from the COMStore.

        Args:
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: Next top k Relevant root modules formatted as a string.
        """
        results = self.com_store.next_entities(
            from_="ROOT_MODULE",
            top_k=top_k
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def next_top_k_code_entities(self, ctx: Context, top_k: int) -> str:
        """
        Retrieve the next set of top k code entities from the COMStore.

        Args:
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: Next top k Relevant code entities formatted as a string.
        """
        results = self.com_store.next_entities(
            from_="CHILDREN",
            top_k=top_k
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def get_info_for_entities(self, ctx: Context, entities: list[str]) -> dict[str, Any]:
        """
        Retrieve information for the given entities from the COMStore.

        Args:
            entities (list[str]): The list of entity names to retrieve information for.

        Returns:
            str: Information about the entities formatted as a string.
        """
        results = self.com_store.get_info_for_entities(entities)

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]

    # Initialize the tools for the agents
    def _init_tools(self):
        """
        Initializes the tools for the workflow.
        """
        rms_tools = [
            FunctionTool.from_defaults(
                fn = self.retrieve_relevant_root_modules
            ),
            FunctionTool.from_defaults(
                fn = self.next_top_k_root_modules
            )
        ]
        ces_tools = [
            FunctionTool.from_defaults(
                fn = self.retrieve_relevant_children_in_subtree
            ),
            FunctionTool.from_defaults(
                fn = self.next_top_k_code_entities
            )
        ]
        cgs_tools = [
            FunctionTool.from_defaults(
                fn = self.get_info_for_entities
            ),
            FunctionTool.from_defaults(
                fn = self.com_store.get_full_path_names,
            ),
        ]

        self.tools = {
            "RootModuleSearcher": rms_tools,
            "CodeEntitySearcher": ces_tools,
            "CodeGenOrchestrator": cgs_tools,
        }

    def _init_agents(self):
        """
        Initializes the agents for the workflow.
        """
        self.root_module_searcher = FunctionAgent(
            name="RootModuleSearcher",
            llm=DEFAULT_LLM,
            system_prompt=ROOT_MODULE_SEARCH_PROMPT,
            tools=self.tools["RootModuleSearcher"],
        )
        self.code_entity_searcher = FunctionAgent(
            name="CodeEntitySearcher",
            llm=DEFAULT_LLM,
            system_prompt=CODE_ENTITY_SEARCH_PROMPT,
            tools=self.tools["CodeEntitySearcher"],
        )
        self.code_gen_orchestrator = FunctionAgent(
            name="CodeGenOrchestrator",
            llm=DEFAULT_LLM,
            tools=self.tools["CodeGenOrchestrator"],
        )

    def _init_sllms(self):
        """
        Initializes the structured LLMs for the workflow.
        """
        self.planner = self.create_structured_llm(
            model_type="advanced",
            output_cls=Plan,
        )
        self.orchestrator = self.create_structured_llm(
            model_type="advanced",
            output_cls=OrchestrationResult,
        )
        self.code_generator = self.create_structured_llm(
            model_type="default",
            output_cls=CodeGenOrchestrationResult,
        )
    
    def __init__(
        self,
        retries: int = 5,     
    ):
        """
        Initializes the MainWkflw with a session ID.
        """
        super().__init__()

        # Initialize the COMStore
        self.com_store = COMStore(
            url=config.NEO4J_URI,
            username=config.NEO4J_USER,
            password=config.NEO4J_PASSWORD,
        )

        # Initialize the tools for the workflow
        self._init_tools()

        # Initialize the agents for the workflow
        self._init_agents()

        # Initialize the structured LLMs for the workflow
        self._init_sllms()

        # Set the retry count for the workflow
        self.retries = retries
    
    # Utility functions
    def prepare_tool_message(self, result_keys: dict[str, Any]) -> ChatMessage:
        """
        Prepares a tool message from the result keys.
        
        Args:
            result_keys (dict[str, str]): The result keys to be included in the tool message.
        
        Returns:
            ChatMessage: The prepared tool message.
        """
        tool_message = "Tool results:"
        for key, value in result_keys.items():
            tool_message += f"\n\n{key}:\n{value}"
        return ChatMessage(role="tool", content=tool_message)
    
    async def run_handler(self, handler: WorkflowHandler) -> dict:
        """
        Runs the workflow handler, logging all steps appropriately.
        
        Args:
            handler (WorkflowHandler): The handler to run the workflow.

        Returns:
            dict: The result of the workflow execution.
        """
        final_response: dict = ""
        current_agent: str = None
        # Run the workflow handler
        async for event in handler.stream_events():
            if (
                hasattr(event, "current_agent_name")
                and event.current_agent_name != current_agent
            ):
                current_agent = event.current_agent_name
                logger.info(f"🤖 Current Agent: {current_agent}")
            elif isinstance(event, AgentOutput):
                if event.response.content:
                    logger.info("📤 Output: " + event.response.content)
                    final_response = event.response.content
                if event.tool_calls:
                    logger.info(
                        "🛠️ Planning to use tools: " +
                        ", ".join([call.tool_name for call in event.tool_calls])
                    )
            elif isinstance(event, ToolCallResult):
                logger.info(f"🔧 Tool Result ({event.tool_name}):")
                logger.info(f"  Arguments: {event.tool_kwargs}")
                logger.info(f"  Output: {event.tool_output}")
            elif isinstance(event, ToolCall):
                logger.info(f"🔨 Calling Tool: {event.tool_name}")
                logger.info(f"  With arguments: {event.tool_kwargs}")

        # Return the final response
        return final_response
    
    async def get_info_for_entities(self, ctx: Context, entities: list[str]) -> str:
        """
        Retrieve information for the given entities from the COMStore.

        Args:
            entities (list[str]): The list of entity names to retrieve information for, preferably as full paths.

        Returns:
            dict[str, Any]: Contains the following keys:
                - "results": Formatted information about the entities.
                - "not_found_entities": Dictionary of entities that were not found in the COMStore, along with retrieved full path name information.
        """
        # Retrieve the results from the COMStore
        results = self.com_store.get_info_for_entities(entities)

        # Iterate through the results and check for which entities the information is not found
        not_found_entity_names = []
        for entity, info in zip(entities, results["raw"]):
            if not info:
                not_found_entity_names.append(entity)

        # Remove the not found entities from the results
        results["raw"] = [info for info in results["raw"] if info]

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        not_found_entities = None
        # If any entities are not found, log a warning. Then, get their full path names and try again
        if not_found_entity_names:
            logger.warning(
                f"Some entities were not found in the COMStore: {', '.join(not_found_entity_names)}. "
                "Attempting to retrieve their full path names and try again."
            )
            # Get the full path names for the not found entities
            not_found_entities = self.com_store.get_full_path_names(not_found_entity_names)

        return {
            "results": results["raw"],
            "not_found_entities": not_found_entities or {}
        }    
    
    def create_structured_llm(self, model_type: str, output_cls: Any) -> LLM:
        """
        Creates a structured LLM based on the model type and output class.
        
        Args:
            model_type (str): The type of the model to create. Accepted values are:
                - "default": Uses the default LLM.
                - "lite": Uses the lite LLM for faster responses.
                - "advanced": Uses the advanced LLM for more complex tasks.
            output_cls (Any): The output class for the structured LLM.
        
        Returns:
            LLM: The created structured LLM.
        """
        if model_type == "default":
            return DEFAULT_LLM.as_structured_llm(output_cls=output_cls)
        elif model_type == "lite":
            return LITE_LLM.as_structured_llm(output_cls=output_cls)
        elif model_type == "advanced":
            return ADVANCED_LLM.as_structured_llm(output_cls=output_cls)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
        
    async def convert_to_structured_output(
        self,
        response: str,
        output_cls: Any,
        model_type: str = "lite",
    ) -> Any:
        """
        Converts the response string to a structured output based on the output class.
        
        Args:
            response (str): The response string to convert.
            output_cls (Any): The output class to convert the response to.
            model_type (str): The type of the model used for conversion. Defaults to "lite".
        
        Returns:
            Any: The converted structured output.
        """
        logger.info("🔄 Converting response to structured output.")
        llm: LLM = DEFAULT_LLM if model_type == "default" else (
            LITE_LLM if model_type == "lite" else ADVANCED_LLM
        )
        structured_response = (
            # For GoogleGenAI, use the following, else structured_predict
            llm.structured_predict_without_function_calling(
                output_cls=output_cls,
                prompt=PromptTemplate(STRUCTURIZE_RESPONSE_PROMPT),
                response=response,
            )
        )

        return structured_response
    
    @step
    async def plan(self, ctx: Context, ev: StartEvent) -> OrchestrationEvent | StopEvent:
        """
        Orchestrates the workflow by analyzing the chat history and determining the next step.
        
        Args:
            ev (StartEvent): The event that triggers the orchestration.
        
        Returns:
            OrchestrationEvent | StopEvent: The event containing the next action to be taken in the workflow.
        """
        # Use the planner to analyze the input prompt and create a plan
        logger.info("📝 Planning the workflow based on the input prompt.")
        planner_result = await self.planner.acomplete(
            prompt=PLAN_PROMPT.format(
                prompt=ev.input,
            )
        )
        plan: Plan = planner_result.raw

        # Set the context with the plan
        state = await ctx.get("state")
        state["plan"] = {
            "objective": plan.objective,
            "requirements": plan.requirements,
        }
        await ctx.set("state", state)

        # If ev.return_direct is True, return the plan directly
        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "objective": plan.objective,
                    "requirements": plan.requirements,
                }
            )

        # Send an empty orchestration event to start the workflow
        logger.info("✅ Plan created successfully. Starting the orchestration workflow.")
        return OrchestrationEvent()
    
    @step
    async def orchestrate(self, ctx: Context, ev: OrchestrationEvent) -> RootModuleSearchEvent | CodeEntitySearchEvent | CodeGenerationEvent | StopEvent:
        """
        Orchestrates the workflow based on the input prompt and chat history.
        
        Args:
            ev (OrchestrationEvent): The event containing the chat history and input prompt.
        
        Returns:
            RootModuleSearchEvent | CodeEntitySearchEvent | CodeGenerationEvent | StopEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the Plan from the context
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")
        plan = state["plan"]

        # Get the orchestrator's chat history from the context
        state = await ctx.get("state")
        if "orchestrator_memory" not in state:
            state["orchestrator_memory"] = Memory.from_defaults(
                token_limit=300000
            )
            # Put the system prompt in the orchestrator memory
            state["orchestrator_memory"].put(
                ChatMessage(
                    role="system",
                    content=ORCHESTRATE_PROMPT.format(
                        objective=plan["objective"],
                        requirements=plan["requirements"],
                    )
                )
            )
        
        # If the OrchestrationEvent has result keys, add them to the orchestrator memory
        if ev.result_keys:
            state["orchestrator_memory"].put(
                self.prepare_tool_message(ev.result_keys)
            )

        orchestrator_memory: Memory = state["orchestrator_memory"]
        chat_history = orchestrator_memory.get()

        # Use the orchestrator to analyze the chat history and determine the next step
        orchestration_result = await self.orchestrator.achat(
            messages=chat_history,
        )
        orchestration_result_json = json.loads(orchestration_result.message.content)
        orchestration_result_model = OrchestrationResult.model_validate_json(orchestration_result_json)

        # Append the orchestration result to the orchestrator memory, and set the state
        orchestrator_memory.put(orchestration_result.message)
        state["orchestrator_memory"] = orchestrator_memory
        await ctx.set("state", state)

        # If ev.return_direct is True, return the orchestration result directly
        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "analysis": orchestration_result_model.analysis,
                    "action": orchestration_result_model.action,
                    "root_module": orchestration_result_model.root_module,
                    "relevant_code_entities": orchestration_result_model.relevant_code_entities,
                    "prompt": orchestration_result_model.prompt,
                }
            )

        # Decide next step based on the orchestration result
        if orchestration_result_model.action == "RootModuleSearchEvent":
            return RootModuleSearchEvent(
                prompt=orchestration_result_model.prompt,
            )
        elif orchestration_result_model.action == "CodeEntitySearchEvent":
            return CodeEntitySearchEvent(
                prompt=orchestration_result_model.prompt,
                root_module=orchestration_result_model.root_module,
            )
        elif orchestration_result_model.action == "CodeGenerationEvent":
            return CodeGenerationEvent(
                prompt=orchestration_result_model.prompt,
                relevant_code_entities=orchestration_result_model.relevant_code_entities or [],
            )
        elif orchestration_result_model.action == "StopEvent":
            return StopEvent()
        else:
            raise ValueError(f"Unknown action: {orchestration_result_model.action}")
        
    @step
    async def root_module_search(self, ctx: Context, ev: RootModuleSearchEvent) -> OrchestrationEvent | StopEvent:
        """
        Searches for root modules in the codebase based on the input prompt.
        
        Args:
            ev (RootModuleSearchEvent): The event containing the input prompt for root module search.
        
        Returns:
            OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the RMS memory from the context
        state = await ctx.get("state")
        if "rms_memory" not in state:
            state["rms_memory"] = Memory.from_defaults(
                token_limit=300000,
            )

        # Get the memory from the state    
        rms_memory: Memory = state["rms_memory"]

        # Extract prompt from the event
        if not ev.prompt:
            raise ValueError("Prompt is required for root module search.")
        else:
            logger.info(f"🔍 Searching for root modules with prompt: {ev.prompt}")

        # Use RootModuleSearcher to search for root modules
        handler = self.root_module_searcher.run(
            user_msg=ev.prompt,
            memory=rms_memory
        )
        final_response: RootModuleSearchResult = None
        retries = self.retries
        while retries > 0:
            response = await self.run_handler(handler)
            final_response = await self.convert_to_structured_output(
                response=response,
                output_cls=RootModuleSearchResult,
            )
            # Check if the agent is done
            if final_response.end:
                break
            retries -= 1

        # If no relevant root modules is found, raise an error
        if not final_response.end or not final_response.relevant_root_modules:
            raise ValueError("No relevant root modules found in the codebase.")

        # Add the pair of prompt and response to the RMS memory
        rms_memory.memory_blocks.append(
            StaticMemoryBlock(
                static_content=f"Prompt: {ev.prompt}\nMost Relevant Root Modules in order of relevance: {', '.join(final_response.relevant_root_modules)}",
            )
        )

        # Set the state with the updated RMS memory
        state["rms_memory"] = rms_memory
        await ctx.set("state", state)

        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "Most Relevant Root Modules in order of relevance": final_response.relevant_root_modules,
                }
            )

        return OrchestrationEvent(
            result_keys={
                "Most Relevant Root Modules in order of relevance": final_response.relevant_root_modules,
            }
        )
    
    @step
    async def code_entity_search(self, ctx: Context, ev: CodeEntitySearchEvent) -> OrchestrationEvent | StopEvent:
        """
        Searches for code entities in the codebase based on the input prompt and root module.
        
        Args:
            ev (CodeEntitySearchEvent): The event containing the input prompt and root module for code entity search.
        
        Returns:
            OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the CES memory from the context
        state = await ctx.get("state")
        if "ces_memory" not in state:
            state["ces_memory"] = Memory.from_defaults(
                token_limit=300000,
            )
        
        # Get the memory from the state
        ces_memory: Memory = state["ces_memory"]

        # Create a prompt for the CodeEntitySearcher
        prompt = f"User Prompt: {ev.get("prompt", "")}\nRoot Module: {ev.root_module}\n\nPlease search for appropriate code entities (functions, classes, methods) in the root module '{ev.root_module}' that are relevant to the user's request, and satisfy the requirements specified in the user prompt."

        # Use CodeEntitySearcher to search for code entities
        handler = self.code_entity_searcher.run(
            user_msg=prompt,
            memory=ces_memory,
        )

        final_response: CodeEntitySearchResult = None
        retries = self.retries
        while retries > 0:
            response = await self.run_handler(handler)
            final_response = await self.convert_to_structured_output(
                response=response,
                output_cls=CodeEntitySearchResult,
            )
            # Check if the agent is done
            if final_response.end:
                break
            retries -= 1
        
        # If no relevant code entity is found, raise an error
        if not final_response.end or not final_response.relevant_code_entities:
            raise ValueError("No relevant code entity found in the codebase.")
        
        # Prepare content string
        content = f"Input: {prompt}\nMost Relevant Code Entities in order of relevance: {', '.join(final_response.relevant_code_entities)}"
        
        # Add the pair of prompt and response to the CES memory
        ces_memory.memory_blocks.append(
            StaticMemoryBlock(
                static_content=content,
            )
        )

        # Set the state with the updated CES memory and relevant code entities
        state["ces_memory"] = ces_memory
        await ctx.set("state", state)

        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "Most Relevant Code Entities in order of relevance": final_response.relevant_code_entities,
                }
            )

        return OrchestrationEvent(
            result_keys={
                "Most Relevant Code Entities in order of relevance": final_response.relevant_code_entities,
            }
        )

    @step
    async def code_generation(self, ctx: Context, ev: CodeGenerationEvent) -> OrchestrationEvent | StopEvent:
        """
        Orchestrates the code generation process based on the input prompt and relevant code entities.
        
        Args:
            ev (CodeGenerationEvent): The event containing the input prompt and relevant code entities for code generation.
        
        Returns:
            ReviewEvent | OrchestrationEvent: The event containing the generated code and analysis, or the next action to be taken in the workflow.
        """
        # Get the relevant code entities from the event
        relevant_code_entities = ev.relevant_code_entities

        # Get the state from the context
        state = await ctx.get("state")

        if not relevant_code_entities:
            raise ValueError("No relevant code entities provided for code generation.")
        
        # Get their information from the COMStore
        results = await self.get_info_for_entities(ctx, relevant_code_entities)

        # If there are any entities that were not found, log a warning and return an OrchestrationEvent
        if results["not_found_entities"]:
            logger.warning(
                f"Some entities were not found in the COMStore: {', '.join(results['not_found_entities'].keys())}. "
                "Please ensure that the entities are correctly defined in the codebase."
            )
            # Store the found entities in the state for later use
            state[""]
            return OrchestrationEvent(
                result_keys={
                    "Entities not found, please check and return correct full path names for the following": results["not_found_entities"],
                }
            )
        
