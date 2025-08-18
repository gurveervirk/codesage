from llama_index.core.workflow import (
    Workflow,
    StartEvent,
    StopEvent,
    Context,
    step,
)
from llama_index.core.workflow.handler import WorkflowHandler
from llama_index.core.workflow.retry_policy import ConstantDelayRetryPolicy
from llama_index.core.agent.workflow import (
    FunctionAgent,
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
    ReplanEvent,
    OrchestrationEvent,
    RootModuleSearchEvent,
    CodeEntitySearchEvent,
    GetEntitiesInfoEvent,
    ProcessFullPathsEvent,
    CodeGenerationEvent,
    EntitiesEvent,
    RespondEvent
)
from backend.utils.wkflw_prompts import (
    PLAN_PROMPT,
    REPLAN_PROMPT,
    ROOT_MODULE_SEARCH_PROMPT,
    CODE_ENTITY_SEARCH_PROMPT,
    PATH_MAPPING_PROMPT,
    CODE_GENERATION_PROMPT,
    STRUCTURIZE_RESPONSE_PROMPT,
    RESPOND_PROMPT,
    RESPOND_FOR_CODE_GENERATION_PROMPT,
    TODO_COMMENTS,
    FORCE_GIVEN_CODE_ENTITIES_ONLY,
)
from backend.code_sage.com_store import (
    COMStore
)
from backend.utils.models import (
    Plan,
    ReplanResult,
    OrchestrationResult,
    RootModuleSearchResult,
    CodeEntitySearchResult,
    PathMapping,
    CodeGenResult,
    create_output_model
)
from backend.config import config
from typing import Any
import json
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the LLM's
default_model_name = "gemini-2.0-flash"  # Default model name
default_model_temperature = 1  # Default temperature for the LLM

lite_model_name = "gemini-2.0-flash-lite"  # Lite model name for faster responses
lite_model_temperature = 1  # Temperature for the lite model

advanced_model_name = "gemini-2.5-flash"  # Advanced model name for more complex tasks
advanced_model_temperature = 1  # Temperature for the advanced model

max_retries = 1  # Maximum number of retries for LLM calls

DEFAULT_LLM: LLM = GoogleGenAI(
    model=default_model_name,
    temperature=default_model_temperature,
    api_key=config.GOOGLE_GENAI_API_KEY,
    max_retries=max_retries,
)

LITE_LLM: LLM = GoogleGenAI(
    model=lite_model_name,
    temperature=lite_model_temperature,
    api_key=config.GOOGLE_GENAI_API_KEY,
    max_retries=max_retries,
)

ADVANCED_LLM: LLM = GoogleGenAI(
    model=advanced_model_name,
    temperature=advanced_model_temperature,
    api_key=config.GOOGLE_GENAI_API_KEY,
    max_retries=max_retries,
)

# TODO: Check embedding model in future, defining a default for now
embed_model = HuggingFaceEmbedding(
    model_name="mixedbread-ai/mxbai-embed-large-v1",
    embed_batch_size=25
)
Settings.embed_model = embed_model

MAX_TODO_CALLS = 3

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
    async def retrieve_relevant_root_modules(self, ctx: Context, query: str) -> dict[str, Any]:
        """
        Retrieve top 10 relevant root modules based on the query, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.

        Returns:
            str: Top 10 Relevant root modules based on the query formatted as a string.
        """
        results = self.com_store.retrieve_relevant_root_modules(
            query=query,
            top_k=10
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def retrieve_relevant_children_in_subtree(self, ctx: Context, query: str, parent_name: str) -> dict[str, Any]:
        """
        Retrieve top 10 relevant children in the subtree based on the query and parent name, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            parent_name (str): The name of the parent module.

        Returns:
            str: Top 10 Relevant children in the subtree based on the query formatted as a string.
        """
        results = self.com_store.retrieve_relevant_children_in_subtree(
            query=query,
            parent_name=parent_name,
            top_k=10
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def next_top_10_root_modules(self, ctx: Context) -> str:
        """
        Retrieve the next set of top 10 root modules from the COMStore.

        Returns:
            str: Next top 10 Relevant root modules formatted as a string.
        """
        results = self.com_store.next_entities(
            from_="ROOT_MODULE",
            top_k=10,
        )

        # Send the raw results as an event
        ctx.send_event(
            EntitiesEvent(
                entities=results["raw"],
            )
        )

        # Return the formatted results
        return results["formatted_results"]
    
    async def next_top_10_code_entities(self, ctx: Context) -> str:
        """
        Retrieve the next set of top 10 code entities from the COMStore.

        Returns:
            str: Next top 10 Relevant code entities formatted as a string.
        """
        results = self.com_store.next_entities(
            from_="CHILDREN",
            top_k=10,
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
                fn = self.next_top_10_root_modules
            )
        ]
        ces_tools = [
            FunctionTool.from_defaults(
                fn = self.retrieve_relevant_children_in_subtree
            ),
            FunctionTool.from_defaults(
                fn = self.next_top_10_code_entities
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
            model_type="default",
            output_cls=Plan,
        )
        self.replanner = self.create_structured_llm(
            model_type="default",
            output_cls=ReplanResult,
        )
        self.orchestrator = self.create_structured_llm(
            model_type="advanced",
            output_cls=OrchestrationResult,
        )
        self.code_generator = self.create_structured_llm(
            model_type="default",
            output_cls=CodeGenResult,
        )
        self.full_path_mapper = self.create_structured_llm(
            model_type="default",
            output_cls=PathMapping,
        )
    
    def __init__(
        self,
        retries: int = 5,
        **kwargs: Any    
    ):
        """
        Initializes the MainWkflw with a session ID.
        """
        super().__init__(
            **kwargs,
        )

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
                logger.info(f"✅ Tool Call Successful!")
            elif isinstance(event, ToolCall):
                logger.info(f"🔨 Calling Tool: {event.tool_name}")
                logger.info(f"  With arguments: {event.tool_kwargs}")

        # Return the final response
        return final_response
    
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
        model_type: str = "default",
    ) -> Any:
        """
        Converts the response string to a structured output based on the output class.
        
        Args:
            response (str): The response string to convert.
            output_cls (Any): The output class to convert the response to.
            model_type (str): The type of the model to use for conversion. Accepted values are:
        
        Returns:
            Any: The converted structured output.
        """
        logger.info("🔄 Converting response to structured output.")
        llm: GoogleGenAI = DEFAULT_LLM if model_type == "default" else (
            LITE_LLM if model_type == "lite" else ADVANCED_LLM
        )
        output_model = create_output_model(output_cls)

        structured_response = llm.structured_predict_without_function_calling(
            prompt=PromptTemplate(
                STRUCTURIZE_RESPONSE_PROMPT.format(
                    response=response,
                )
            ),
            output_cls=output_model,
        )
        logging.info("🔄 Response converted to structured output successfully.")
        return structured_response
    
    def extract_todo_comments(
        self,
        response: str,
    ) -> list[str]:
        """
        Extracts todo comments from the response string. Specifically retrieves the part after `todo:`.
        
        Args:
            response (str): The response string to extract todo comments from.
        
        Returns:
            list[str]: A list of todo comments extracted from the response.
        """
        # Use a regex to find all todo comments in the response
        result = re.findall(
            r"(?i)TODO:\s*(.*?)(?=\n|$)",
            response,
            re.DOTALL,
        )
        # Strip whitespace from each todo comment
        todo_comments = [todo.strip() for todo in result if todo.strip()]

        return todo_comments

    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
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
        plan: dict = planner_result.raw.model_dump()
        num_requirements = len(plan.get("requirements", []))

        # Convert list of dict of requirements to a dict of requirements
        if isinstance(plan["requirements"], list):
            plan["requirements"] = {
                req["key"]: req for req in plan["requirements"]
            }
            # Drop the `key` from each requirement
            for key in plan["requirements"]:
                if "key" in plan["requirements"][key]:
                    del plan["requirements"][key]["key"]

        # Add `completed` key to the plan, for each requirement
        for key in plan["requirements"]:
            plan["requirements"][key]["completed"] = False

        # Add `output` key to the plan, for each requirement
        for key in plan["requirements"]:
            plan["requirements"][key]["output"] = None

        # Add `has_code_gen` key to the plan, set based on whether any requirement is of type "CG"
        plan["has_code_gen"] = any(
            plan["requirements"][key]["requirement_type"] == "CG" for key in plan["requirements"]
        )

        # Set the context with the plan and the original input prompt
        state = await ctx.get("state")
        state["plan"] = plan
        state["input_prompt"] = ev.input
        await ctx.set("state", state)

        # If ev.return_direct is True, return the plan directly
        if ev.get("return_direct", False):
            return StopEvent(
                result_keys=plan
            )

        # Send an empty orchestration event to start the workflow
        logger.info(f"✅ Plan created successfully with {num_requirements} steps. Starting the orchestration workflow.")
        return OrchestrationEvent()

    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def replan(self, ctx: Context, ev: ReplanEvent) -> OrchestrationEvent | StopEvent:
        """
        Replans the workflow based on the chat history and input prompt.

        Args:
            ev (ReplanEvent): The event containing the chat history and input prompt.

        Returns:
            OrchestrationEvent | StopEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the state and problem
        problem: str = ev.get("problem", "")
        if not problem:
            raise ValueError("Problem not provided in the ReplanEvent.")
        state = await ctx.get("state")
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")

        # Get the Plan and original input from the state
        plan = state["plan"]
        original_input = state.get("input_prompt", "")

        # Replan
        logger.info("🔄 Replanning the workflow based on the state and problem")
        replan_result = await self.replanner.acomplete(
            prompt=REPLAN_PROMPT.format(
                original_input=original_input,
                problem=problem,
                plan=json.dumps(plan, indent=2),
            )
        )

        replan_result: ReplanResult = replan_result.raw

        for key in replan_result.keys_to_remove:
            if key in plan["requirements"]:
                del plan["requirements"][key]
                logger.info(f"🗑️ Removed requirement: {key}")

        for new_requirement in replan_result.new_requirements:
            if new_requirement.key in plan["requirements"]:
                logger.info(f"🔄 Updated existing requirement: {new_requirement.key}")
            else:
                logger.info(f"➕ Added new requirement: {new_requirement.key}")
            plan["requirements"][new_requirement.key] = {
                "query": new_requirement.query,
                "requirement_type": new_requirement.requirement_type,
                "completed": False,
                "output": None,
                "dependency": new_requirement.dependency,
            }

        # Update the plan in the state
        state["plan"] = plan
        await ctx.set("state", state)

        # If ev.return_direct is True, return the plan directly
        if ev.get("return_direct", False):
            return StopEvent(
                result_keys=plan
            )

        # Send an empty orchestration event to start the workflow
        logger.info("✅ Replan completed successfully. Starting the orchestration workflow.")
        return OrchestrationEvent(
            return_direct=ev.get("return_direct", False),
        )
        
    
    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def orchestrate(self, ctx: Context, ev: OrchestrationEvent) -> RootModuleSearchEvent | CodeEntitySearchEvent | GetEntitiesInfoEvent | StopEvent | RespondEvent:
        """
        Orchestrates the workflow based on the input prompt and chat history.
        
        Args:
            ev (OrchestrationEvent): The event containing the chat history and input prompt.
        
        Returns:
            RootModuleSearchEvent | CodeEntitySearchEvent | GetEntitiesInfoEvent | StopEvent | RespondEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the state from the context
        state = await ctx.get("state")

        # Get the Plan from the context
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")
        plan = state["plan"]

        # If the plan is empty, raise an error
        if not plan or not isinstance(plan, dict):
            raise ValueError("Plan is empty or not a valid dictionary.")
        
        # If the plan has no requirements, raise an error
        if "requirements" not in plan or not plan["requirements"]:
            raise ValueError("Plan has no requirements to fulfill.")
        
        # Check if the plan has any requirements that are not completed and execute the next step
        requirements: dict = plan["requirements"]
        remaining_requirements = [
            req for req in plan["requirements"] if not requirements[req]["completed"]
        ]

        if not remaining_requirements:
            logger.info("✅ All requirements are completed. Responding with the final results.")
            # If all requirements are completed, respond with the final results
            return RespondEvent()

        # Get the next requirement to fulfill
        for key in remaining_requirements:
            next_requirement = requirements[key]
            logger.info(f"🔍 Next requirement to fulfill: {key} - {next_requirement["query"]}")

            # Check the requirement type and decide the next step
            if next_requirement["requirement_type"] == "RMS":
                return RootModuleSearchEvent(
                    key=key,
                    return_direct=ev.get("return_direct", False),
                )
            
            elif next_requirement["requirement_type"] == "CES":
                # `Eagerly` check if it's dependency has been fulfilled
                dependency = next_requirement.get("dependency")
                if not requirements[dependency]["completed"]:
                    continue  # Skip this requirement if its dependency is not fulfilled
                
                return CodeEntitySearchEvent(
                    key=key,
                    return_direct=ev.get("return_direct", False),
                )
            
            elif next_requirement["requirement_type"] == "CG":
                logger.info("🔍 Preparing for code generation based on the requirement.")
                # Check if all other steps have been completed before proceeding to code generation
                if len(remaining_requirements) > 1:
                    continue  # Skip this requirement if there are other requirements to fulfill
                
                # Initiate code generation using GetEntitiesInfoEvent
                return GetEntitiesInfoEvent()
            
            else:
                raise ValueError(f"Unknown requirement type: {next_requirement['requirement_type']}")
        
    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def root_module_search(self, ctx: Context, ev: RootModuleSearchEvent) -> OrchestrationEvent | ReplanEvent | StopEvent:
        """
        Searches for root modules in the codebase based on the input prompt.
        
        Args:
            ev (RootModuleSearchEvent): The event containing the input prompt for root module search.
        
        Returns:
            OrchestrationEvent | ReplanEvent | StopEvent: The event containing the next action to be taken in the workflow.
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
        prompt = None
        if ev.key:
            # If a key is provided, get the prompt from the plan
            if "plan" not in state or "requirements" not in state["plan"]:
                raise ValueError("Plan not found in the context state.")
            plan = state["plan"]
            if ev.key not in plan["requirements"]:
                raise ValueError(f"Requirement with key '{ev.key}' not found in the plan.")
            prompt = plan["requirements"][ev.key]["query"]
        elif ev.prompt:
            # If a prompt is provided, use it directly
            prompt = ev.prompt
        else:
            raise ValueError("Either a key or a prompt must be provided for root module search.")
        
        original_input = state.get("input_prompt", "")
        prompt = f"Original Input: {original_input}\nUser Prompt: {prompt}"

        logger.info(f"🔍 Searching for root modules based on the prompt: {prompt}")

        # Create a function to reinitialize the handler for root module search
        def get_handler():
            return self.root_module_searcher.run(
                user_msg=prompt,
                memory=rms_memory,
            )
        
        handler = get_handler()
        final_response: RootModuleSearchResult = None
        retries = self.retries
        while retries > 0:
            response = await self.run_handler(handler)
            final_response = await self.convert_to_structured_output(
                response=response,
                output_cls=RootModuleSearchResult,
            )
            # Check if the agent is done
            if final_response.end_args.end:
                break
            retries -= 1
            handler = get_handler()  # Reinitialize the handler for the next iteration

        # If no relevant root modules is found, raise an error
        if not final_response.end_args.end or not final_response.most_relevant_root_module:
            raise ValueError("No relevant root modules found in the codebase.")
        
        # If search failed, replan
        if final_response.end_args.end_type == "failure":
            if ev.get("return_direct", False):
                return StopEvent(
                    result_keys={
                        "error": "Root module search failed. Replanning required.",
                    }
                )
            logger.error("❌ Root module search failed. Replanning...")
            return ReplanEvent(
                problem=f"Root module search failed with error: {final_response.end_args.reason}",
                return_direct=ev.get("return_direct", False),
            )

        # Add the pair of prompt and response to the RMS memory
        rms_memory.memory_blocks.append(
            StaticMemoryBlock(
                static_content=f"Prompt: {ev.prompt}\nMost Relevant Root Module: {final_response.most_relevant_root_module}",
            )
        )

        # Set the state with the updated RMS memory
        state["rms_memory"] = rms_memory

        # If key is provided, update the plan with the relevant root modules as output
        if ev.key:
            if "plan" not in state or "requirements" not in state["plan"]:
                raise ValueError("Plan not found in the context state.")
            plan = state["plan"]
            if ev.key not in plan["requirements"]:
                raise ValueError(f"Requirement with key '{ev.key}' not found in the plan.")
            plan["requirements"][ev.key]["output"] = final_response.most_relevant_root_module
            state["plan"] = plan

            # Set `completed` to True for the requirement
            plan["requirements"][ev.key]["completed"] = True

        # Set the state in the context
        await ctx.set("state", state)

        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "Most Relevant Root Module": final_response.most_relevant_root_module,
                }
            )

        return OrchestrationEvent(
            result_keys={
                "Most Relevant Root Module": final_response.most_relevant_root_module,
            }
        )
    
    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
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
        prompt = None
        root_module = None
        output = None
        recheck = False
        if ev.key:
            # If a key is provided, get the prompt and root module from the plan
            if "plan" not in state or "requirements" not in state["plan"]:
                raise ValueError("Plan not found in the context state.")
            plan = state["plan"]
            if ev.key not in plan["requirements"]:
                raise ValueError(f"Requirement with key '{ev.key}' not found in the plan.")
            prompt = plan["requirements"][ev.key]["query"]
            dependency = plan["requirements"][ev.key].get("dependency")
            if not dependency:
                raise ValueError(f"Dependency for requirement '{ev.key}' not found in the plan.")
            if dependency not in plan["requirements"]:
                raise ValueError(f"Dependency '{dependency}' not found in the plan.")
            if not plan["requirements"][dependency]["completed"]:
                raise ValueError(f"Dependency '{dependency}' is not completed.")
            root_module = plan["requirements"][dependency].get("output")

            output = plan["requirements"][ev.key].get("output")
            if output is not None and type(output) is dict:
                # This means the current_output was not provided correctly and needs to be rechecked
                output = output.get("current_output")
                recheck = True
        
        elif ev.prompt and ev.root_module:
            # If a prompt is provided, use it directly
            prompt = ev.prompt
            root_module = ev.root_module

        else:
            raise ValueError("Either a key or both a prompt and root module must be provided for code entity search.")
        
        if not prompt or not root_module:
            raise ValueError("Prompt and root module must be provided for code entity search.")
        
        original_input = state.get("input_prompt", "")
        if not original_input:
            raise ValueError("Original input not found in the context state.")
        
        if recheck:
            prompt = f"Original Input: {original_input}\nUser Prompt: {prompt}\nRoot Module: {root_module}\nCurrent Output: {output}\n\nPlease recheck the current output as it is not provided correctly. Find the correct code entity based on the provided current output and other details."
        else:
            prompt = f"Original Input: {original_input}\nUser Prompt: {prompt}\nRoot Module: {root_module}\n\nPlease search for appropriate code entities (functions, classes, methods) in the root module '{root_module}' that are relevant to the user's request, and satisfy the requirements specified in the user prompt."

        # Create a function to reinitialize the handler for code entity search
        def get_handler():
            return self.code_entity_searcher.run(
                user_msg=prompt,
                memory=ces_memory,
            )
        
        handler = get_handler()

        final_response: CodeEntitySearchResult = None
        retries = self.retries
        while retries > 0:
            response = await self.run_handler(handler)
            final_response = await self.convert_to_structured_output(
                response=response,
                output_cls=CodeEntitySearchResult,
            )
            # Check if the agent is done
            if final_response.end_args.end:
                break
            retries -= 1
            handler = get_handler()  # Reinitialize the handler for the next iteration
        
        # If no relevant code entity is found, raise an error
        if not final_response.end_args.end or not final_response.most_relevant_code_entity:
            raise ValueError("No relevant code entity found in the codebase.")
        
        # If search failed, replan
        if final_response.end_args.end_type == "failure":
            if ev.get("return_direct", False):
                return StopEvent(
                    result_keys={
                        "error": "Code entity search failed. Replanning required.",
                    }
                )
            logger.error("❌ Code entity search failed. Replanning...")
            return ReplanEvent(
                problem=f"Code entity search failed with error: {final_response.end_args.reason}",
                return_direct=ev.get("return_direct", False),
            )

        # Prepare content string
        content = f"Input: {prompt}\nMost Relevant Code Entity: {final_response.most_relevant_code_entity}"
        
        # Add the pair of prompt and response to the CES memory
        ces_memory.memory_blocks.append(
            StaticMemoryBlock(
                static_content=content,
            )
        )

        # Set the state with the updated CES memory and relevant code entities
        state["ces_memory"] = ces_memory

        # If key is provided, update the plan with the relevant code entities as output
        if ev.key:
            if "plan" not in state or "requirements" not in state["plan"]:
                raise ValueError("Plan not found in the context state.")
            plan = state["plan"]
            if ev.key not in plan["requirements"]:
                raise ValueError(f"Requirement with key '{ev.key}' not found in the plan.")
            plan["requirements"][ev.key]["output"] = final_response.most_relevant_code_entity
            state["plan"] = plan

            # Set `completed` to True for the requirement
            plan["requirements"][ev.key]["completed"] = True

        # Set the state in the context
        await ctx.set("state", state)

        if ev.get("return_direct", False):
            return StopEvent(
                result_keys={
                    "Most Relevant Code Entity": final_response.most_relevant_code_entity,
                }
            )

        return OrchestrationEvent(
            result_keys={
                "Most Relevant Code Entity": final_response.most_relevant_code_entity,
            }
        )
    
    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def check_then_get_info_for_entities(self, ctx: Context, ev: GetEntitiesInfoEvent) -> OrchestrationEvent | CodeGenerationEvent | ProcessFullPathsEvent | StopEvent:
        """
        Check if all requirements in the plan are fulfilled, and if so, retrieve information for the relevant entities from the COMStore.

        Args:
            ctx (Context): The context of the workflow.
            ev (GetEntitiesInfoEvent): A dummy event to trigger the step.

        Returns:
            OrchestrationEvent | CodeGenerationEvent | ProcessFullPathsEvent | StopEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the state from the context
        state = await ctx.get("state")

        # Get the plan from the context
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")

        plan = state["plan"]

        # Check if all CE requirements are fulfilled, and get their
        requirements: dict = plan["requirements"]
        entities = []
        not_found_entities = []
        recheck_entities = []
        not_completed_keys = []
        recheck_keys = []
        outputs = {}
        full_paths = {}
        for key in requirements:
            if requirements[key]["requirement_type"] != "CES":
                continue
            if not requirements[key]["completed"] or not requirements[key]["output"]:
                not_completed_keys.append(key)
                continue
            if type(requirements[key]["output"])is str:
                entities.append(requirements[key]["output"])

        if not entities:
            logger.info("No entities to retrieve information for. Skipping.")
            return

        # Get information for the entities
        logger.info(f"Retrieving information for entities...")
        results = self.com_store.get_info_for_entities(entities)

        # Process the results
        for entity, result in zip(entities, results["formatted_results"]):
            if result is None:
                not_found_entities.append(entity)
                continue
            outputs[entity] = result
        
        # Get full path names for the not found entities
        if not_found_entities:
            entities = []
            full_path_to_entity = {}
            logger.info(f"Retrieving full path names for not found entities...")
            full_path_results = await self.com_store.get_full_path_names(not_found_entities)
            for entity, full_path_dict in zip(not_found_entities, full_path_results):
                if full_path_dict["no_match"]:
                    recheck_entities.append(entity)
                elif full_path_dict["exact_match"]:
                    entities.append(full_path_dict["exact_match"])
                    full_path_to_entity[entity] = full_path_dict["exact_match"]
                else:
                    full_paths[entity] = full_path_dict["best_matches"]

            # For exact matches, rerun the information retrieval
            if entities:
                logger.info(f"Retrieving information for exact matches...")
                exact_results = self.com_store.get_info_for_entities(entities)
                for entity, result in zip(entities, exact_results["formatted_results"]):
                    outputs[full_path_to_entity[entity]] = result

        # Store all outputs in the state
        for key in requirements:
            if requirements[key]["requirement_type"] != "CES":
                continue
            if not requirements[key]["completed"] or not requirements[key]["output"]:
                continue
            if requirements[key]["output"] in outputs:
                requirements[key]["output"] = outputs[requirements[key]["output"]]
            elif requirements[key]["output"] in recheck_entities:
                recheck_keys.append(key)

        # If there are not_completed or recheck keys, finish them
        if not_completed_keys or recheck_keys:
            for key in not_completed_keys:
                plan["requirements"][key]["completed"] = False
            for key in recheck_keys:
                plan["requirements"][key]["completed"] = False
                plan["requirements"][key]["output"] = {
                    "current_output": plan["requirements"][key]["output"],
                    "recheck": True,
                }

        # Update the plan in the state
        plan["requirements"] = requirements
        state["plan"] = plan
        await ctx.set("state", state)

        if not_completed_keys or recheck_keys:
            # If there are not_completed or recheck keys, return an OrchestrationEvent to handle them
            return OrchestrationEvent(
                result_keys={
                    "not_completed_keys": not_completed_keys,
                    "recheck_keys": recheck_keys,
                }
            )

        if full_paths:
            # If there are full paths to check, return a ProcessFullPathsEvent to handle them
            return ProcessFullPathsEvent(
                full_paths=full_paths,
            )

        # If all requirements are fulfilled, return a CodeGenerationEvent to proceed with code generation
        return CodeGenerationEvent(
            return_direct=ev.get("return_direct", False),
        )
    
    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def check_full_paths(self, ctx: Context, ev: ProcessFullPathsEvent) -> GetEntitiesInfoEvent:
        """
        Check full paths using AI and decide the right full path for the incorrect path

        Args:
            full_paths (dict[str, list[str]]): A dictionary where keys are entity names and values are lists of possible full paths.

        Returns:
            GetEntitiesInfoEvent: An event containing the correct paths for the entities.
        """
        full_paths = ev.full_paths
        state = await ctx.get("state")
        plan = state.get("plan", {})
        if not plan or "requirements" not in plan:
            raise ValueError("Plan not found in the context state.")

        if not full_paths:
            raise ValueError("No full paths provided for the entities.")

        # Create a structured LLM for path mapping
        llm: GoogleGenAI = self.create_structured_llm(
            model_type="default",
            output_cls=PathMapping,
        )

        # Prepare the prompt for path mapping
        prompt = PATH_MAPPING_PROMPT.format(
            full_paths=json.dumps(full_paths, indent=2),
        )

        # Get the path mapping from the LLM
        path_mapping: PathMapping = llm.structured_predict_without_function_calling(
            prompt=PromptTemplate(prompt),
            output_cls=PathMapping,
        )

        # Convert the path mapping to a dictionary
        result = {item["incorrect_path"]: item["correct_path"] for item in path_mapping.path_mapping}

        # Update the plan with the correct paths
        for key in plan["requirements"]:
            if plan["requirements"][key]["requirement_type"] == "CES":
                if plan["requirements"][key]["output"] in result:
                    plan["requirements"][key]["output"] = result[plan["requirements"][key]["output"]]
                    
        # Update the state with the new plan
        state["plan"] = plan
        await ctx.set("state", state)

        return GetEntitiesInfoEvent()

    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def code_generation(self, ctx: Context, ev: CodeGenerationEvent) -> OrchestrationEvent | RespondEvent:
        """
        Orchestrates the code generation process based on the input prompt and relevant code entities.
        
        Args:
            ev (CodeGenerationEvent): The event containing the input prompt and relevant code entities for code generation.
        
        Returns:
            OrchestrationEvent | RespondEvent: The event containing the next action to be taken in the workflow.
        """
        # Get information for the relevant code entities
        state = await ctx.get("state")
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")
        plan = state["plan"]

        if "todo_calls" not in state:
            state["todo_calls"] = 0
        
        todo_calls = state["todo_calls"]

        # Get CG requirement key from the event and set the code as it's output
        cg_key = None
        for key in plan["requirements"]:
            if plan["requirements"][key]["requirement_type"] == "CG":
                cg_key = key
        
        # Get the relevant code entities from the plan
        relevant_code_entities = {}
        for key in plan["requirements"]:
            if plan["requirements"][key]["requirement_type"] == "CES":
                if plan["requirements"][key]["completed"]:
                    # Key is query and value is the output
                    relevant_code_entities[plan["requirements"][key]["query"]] = plan["requirements"][key]["output"]
                else:
                    logger.warning(f"Requirement {key} is not completed, skipping it.")

        if not relevant_code_entities:
            raise ValueError("No relevant code entities found in the plan.")

        # Prepare the input prompt for code generation
        input_prompt = state.get("input_prompt", "")
        if not input_prompt:
            raise ValueError("Input prompt not found in the plan.")
        
        # Get the previous code from the plan if available
        previous_code = plan["requirements"][cg_key].get("output", None)

        code_output = await self.code_generator.acomplete(
            prompt=CODE_GENERATION_PROMPT.format(
                prompt=input_prompt,
                relevant_code_entities=json.dumps(relevant_code_entities, indent=2),
                previous_code=previous_code if previous_code else "No previous code available.",
                todo_comments_allowance=TODO_COMMENTS if todo_calls < MAX_TODO_CALLS else FORCE_GIVEN_CODE_ENTITIES_ONLY,
            )
        )

        code_output: CodeGenResult = code_output.raw

        # Extract todo comments from the generated code using Python
        code = code_output.code

        # If no code is generated, raise an error
        if not code:
            raise ValueError("No code generated by the LLM.")
        
        # Set the code as the output of the CG requirement
        plan["requirements"][cg_key]["output"] = code
        plan["requirements"][cg_key]["completed"] = True

        todo_comments = self.extract_todo_comments(code)

        if todo_comments:
            logger.info(f"Found TODO comments in the generated code... Running steps to get more information...")
            plan["requirements"][cg_key]["completed"] = False  # Mark the CG requirement as not completed yet
            # If there are todo comments, put them as requirements in the plan
            for todo in todo_comments:
                # Get a random 4 character key for the todo using state
                if state.get("todo_key_counter") is None:
                    state["todo_key_counter"] = 0

                state["todo_key_counter"] += 1
                rms_todo_key = f"RMS_TODO_{state['todo_key_counter']}"
                ces_todo_key = f"CES_TODO_{state['todo_key_counter']}"

                # Add RMS and CES requirements for the todo comments
                plan["requirements"][rms_todo_key] = {
                    "query": f"Python module for {todo}",
                    "requirement_type": "RMS",
                    "completed": False,
                    "output": None,
                }
                plan["requirements"][ces_todo_key] = {
                    "query": f"Find code entities for {todo}",
                    "requirement_type": "CES",
                    "completed": False,
                    "output": None,
                    "dependency": rms_todo_key,  # Dependency on the RMS requirement
                }
            
            # Increment the todo_calls counter
            todo_calls += 1

        # Update the plan in the state
        state["plan"] = plan
        await ctx.set("state", state)

        if todo_comments:
            return OrchestrationEvent(
                result_keys={
                    "todo_comments": todo_comments,
                }
            )

        # If no todo comments, respond with the generated code
        logger.info("✅ Code generation completed successfully. Responding with the generated code.")
        return RespondEvent(
            return_direct=ev.get("return_direct", False),
        )

    @step(retry_policy=ConstantDelayRetryPolicy(delay=5, maximum_attempts=3))
    async def respond(self, ctx: Context, ev: RespondEvent) -> StopEvent:
        """
        Responds to the user with the final output of the workflow.
        
        Args:
            ev (RespondEvent): The event containing the final output to be sent to the user.
        
        Returns:
            StopEvent: The event indicating the end of the workflow.
        """
        # Get the state from the context
        state = await ctx.get("state")

        # If there are no outputs, raise an error
        if "plan" not in state:
            raise ValueError("Plan not found in the context state.")
        
        plan = state["plan"]
        response = None

        # If the plan required code generation, provide an explanation of the generated code
        if plan.get("has_code_gen", False):
            # Prepare the response with an explanation of the generated code
            response = await LITE_LLM.acomplete(
                prompt=RESPOND_FOR_CODE_GENERATION_PROMPT.format(
                    input=state["input_prompt"],
                    plan=state["plan"],
                )
            )
        else:
            # If no code generation was required, prepare a simple response
            response = await LITE_LLM.acomplete(
                prompt=RESPOND_PROMPT.format(
                    input=state["input_prompt"],
                    plan=state["plan"],
                )
            )

        # If the response is empty, raise an error
        if not response or not response.text:
            raise ValueError("No response generated by the LLM.")
        
        # Prepare the final response
        if plan.get("has_code_gen", False):
            code = None
            for key in plan["requirements"]:
                if plan["requirements"][key]["requirement_type"] == "CG":
                    code = plan["requirements"][key]["output"]
                    break

            response = f"```python\n{code}\n```\n\n{response.text.strip()}"
        else:
            response = response.text.strip()

        logger.info("📤 Final Response Generated! Cleaning up...")

        # Clean up the state
        state["todo_key_counter"] = 0
        state["todo_calls"] = 0

        await ctx.set("state", state)
        
        return StopEvent(
            result=response
        )