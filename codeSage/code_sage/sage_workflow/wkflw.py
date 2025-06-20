from llama_index.core.workflow import (
    Workflow,
    StartEvent,
    StopEvent,
    Context,
    step,
)
from llama_index.core.agent.workflow import (
    FunctionAgent,
)
from llama_index.core.tools import FunctionTool
from llama_index.core.llms import LLM, ChatMessage
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.core.memory import Memory
from code_sage.sage_workflow.events import (
    OrchestrationEvent,
    RootModuleSearchEvent,
    CodeEntitySearchEvent,
    CodeGenerationEvent,
    ReviewEvent,
    COMRootModuleSearchEvent,
    COMCodeEntitySearchEvent,
    COMEntityInfoRetrievalEvent,
    EntitiesEvent
)
from utils.wkflw_prompts import (
    PLAN_PROMPT,
    ORCHESTRATE_PROMPT,
    ROOT_MODULE_SEARCH_PROMPT,
    CODE_ENTITY_SEARCH_PROMPT,
    CODE_GENERATION_PROMPT,
    REVIEW_PROMPT,
)
from code_sage.com_store import (
    COMStore
)
from utils.models import (
    Plan,
    OrchestrationResult,
    RootModuleSearchResult,
    CodeEntitySearchResult,
    CodeGenOrchestrationResult,
)
from typing import Any
import json

BASE_LLM: LLM = GoogleGenAI(
    model="gemini-2.0-flash",
    temperature=0.2,
)

class MainWkflw(Workflow):
    """
    A workflow for:
    - Fetching relevant code entities for requested functionalities
    - Generating code based on these entities
    - Reviewing the generated code for correctness, functionality, and best practices
    """
    com_store: COMStore = COMStore()
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
        await ctx.send_event(
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
        await ctx.send_event(
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
        await ctx.send_event(
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
        await ctx.send_event(
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
        await ctx.send_event(
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
            )
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
            llm=BASE_LLM.as_structured_llm(
                output_cls=RootModuleSearchResult,
            ),
            tools=self.tools["RootModuleSearcher"],
        )
        self.code_entity_searcher = FunctionAgent(
            name="CodeEntitySearcher",
            llm=BASE_LLM.as_structured_llm(
                output_cls=CodeEntitySearchResult,
            ),
            tools=self.tools["CodeEntitySearcher"],
        )
        self.code_gen_orchestrator = FunctionAgent(
            name="CodeGenOrchestrator",
            llm=BASE_LLM.as_structured_llm(
                output_cls=CodeGenOrchestrationResult,
            ),
            tools=self.tools["CodeGenOrchestrator"],
        )

    def _init_sllms(self):
        """
        Initializes the structured LLMs for the workflow.
        """
        self.planner = BASE_LLM.as_structured_llm(
            output_cls=Plan,
        )
        self.orchestrator = BASE_LLM.as_structured_llm(
            output_cls=OrchestrationResult,
        )
        self.code_generator = BASE_LLM.as_structured_llm(
            output_cls=CodeGenerationResult,
        )

    
    def __init__(self):
        """
        Initializes the MainWkflw with a session ID.
        """
        super().__init__()

        # Initialize the tools for the workflow
        self._init_tools()

        # Initialize the agents for the workflow
        self._init_agents()

        # Initialize the structured LLMs for the workflow
        self._init_sllms()
    
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
    
    @step
    async def plan(self, ctx: Context, ev: StartEvent) -> OrchestrationEvent:
        """
        Orchestrates the workflow by analyzing the chat history and determining the next step.
        
        Args:
            ev (StartEvent): The event that triggers the orchestration.
        
        Returns:
            OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Use the planner to analyze the input prompt and create a plan
        planner_result = await self.planner.acomplete(
            prompt=PLAN_PROMPT.format(
                prompt=ev.input,
            )
        )
        plan = json.loads(planner_result)
        plan = Plan.model_validate_json(plan)

        # Set the context with the plan
        state = await ctx.get("state")
        state["plan"] = {
            "objective": plan.objective,
            "requirements": plan.requirements,
        }
        await ctx.set("state", state)

        # Send an empty orchestration event to start the workflow
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

        # Decide next step based on the orchestration result
        if orchestration_result_model.action == "RootModuleSearchEvent":
            return RootModuleSearchEvent(
                manual=False,
                prompt=orchestration_result_model.prompt,
            )
        elif orchestration_result_model.action == "CodeEntitySearchEvent":
            return CodeEntitySearchEvent(
                manual=False,
                prompt=orchestration_result_model.prompt,
                root_module=orchestration_result_model.root_module,
            )
        elif orchestration_result_model.action == "CodeGenerationEvent":
            # Retrieve relevant code entities from the context
            relevant_code_entities = state.get("relevant_code_entities", [])
            if not relevant_code_entities:
                raise ValueError("No relevant code entities found in the context state.")
            return CodeGenerationEvent(
                manual=False,
                prompt=orchestration_result_model.prompt,
                relevant_code_entities=relevant_code_entities,
            )
        elif orchestration_result_model.action == "EndEvent":
            return StopEvent()
        else:
            raise ValueError(f"Unknown action: {orchestration_result_model.action}")
        
    @step
    async def root_module_search(self, ctx: Context, ev: RootModuleSearchEvent) -> COMRootModuleSearchEvent | OrchestrationEvent:
        """
        Searches for root modules in the codebase based on the input prompt.
        
        Args:
            ev (RootModuleSearchEvent): The event containing the input prompt for root module search.
        
        Returns:
            COMRootModuleSearchEvent | OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the RMS memory from the context
        state = await ctx.get("state")
        if "rms_memory" not in state:
            state["rms_memory"] = Memory.from_defaults(
                token_limit=300000
            )
            # Put the system prompt in the RMS memory
            state["rms_memory"].put(
                ChatMessage(
                    role="system",
                    content=ROOT_MODULE_SEARCH_PROMPT.format(
                        prompt=ev.prompt,
                    )
                )
            )

        if ev.result_keys:
            # If the RootModuleSearchEvent has result keys, add them to the RMS memory
            state["rms_memory"].put(
                self.prepare_tool_message(ev.result_keys)
            )
        
        rms_memory: Memory = state["rms_memory"]
        chat_history = rms_memory.get()

        # Use RootModuleSearcher to search for root modules
        root_module_search_result = await self.root_module_searcher.achat(
            messages=chat_history,
        )

        root_module_search_result_json = json.loads(root_module_search_result.message.content)
        root_module_search_result_model = RootModuleSearchResult.model_validate_json(root_module_search_result_json)

        # Append the root module search result to the RMS memory, and set the state
        rms_memory.put(root_module_search_result.message)
        state["rms_memory"] = rms_memory
        await ctx.set("state", state)

        # Decide next step based on the root module search result
        if root_module_search_result_model.action == "Search":
            return COMRootModuleSearchEvent(
                manual=False,
                prompt=root_module_search_result_model.prompt,
            )
        
        elif root_module_search_result_model.action == "Next":
            return COMRootModuleSearchEvent(
                manual=False,
                next=True,
                prompt=root_module_search_result_model.prompt,
            )
        elif root_module_search_result_model.action == "End":
            # Return an orchestration event to continue the workflow
            return OrchestrationEvent(
                result_keys={
                    "root_module": root_module_search_result_model.root_module,
                    "runner_up_modules": root_module_search_result_model.runner_up_modules,
                }
            )
        else:
            raise ValueError(f"Unknown action: {root_module_search_result_model.action}")
    
    @step
    async def code_entity_search(self, ctx: Context, ev: CodeEntitySearchEvent) -> COMCodeEntitySearchEvent | OrchestrationEvent:
        """
        Searches for code entities in the codebase based on the input prompt and root module.
        
        Args:
            ev (CodeEntitySearchEvent): The event containing the input prompt and root module for code entity search.
        
        Returns:
            COMCodeEntitySearchEvent | OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the CES memory from the context
        state = await ctx.get("state")
        if "ces_memory" not in state:
            state["ces_memory"] = Memory.from_defaults(
                token_limit=300000
            )
            if not ev.root_module:
                raise ValueError("Root Module must be provided for CodeEntitySearchEvent.")
            # Put the system prompt in the CES memory
            state["ces_memory"].put(
                ChatMessage(
                    role="system",
                    content=CODE_ENTITY_SEARCH_PROMPT.format(
                        prompt=ev.prompt,
                        root_module=ev.root_module
                    )
                )
            )

        if ev.result_keys:
            # If the CodeEntitySearchEvent has result keys, add them to the CES memory
            state["ces_memory"].put(
                self.prepare_tool_message(ev.result_keys)
            )
        
        ces_memory: Memory = state["ces_memory"]
        chat_history = ces_memory.get()

        # Use CodeEntitySearcher to search for code entities
        code_entity_search_result = await BASE_LLM.achat(
            messages=chat_history,
        )

        code_entity_search_result_json = json.loads(code_entity_search_result.message.content)
        code_entity_search_result_model = CodeEntitySearchResult.model_validate_json(code_entity_search_result_json)

        # Append the code entity search result to the CES memory, and set the state
        ces_memory.put(code_entity_search_result.message)
        state["ces_memory"] = ces_memory
        await ctx.set("state", state)

        # Decide next step based on the code entity search result
        if code_entity_search_result_model.action == "Search":
            return COMCodeEntitySearchEvent(
                manual=False,
                prompt=code_entity_search_result_model.prompt,
                parent=code_entity_search_result_model.parent,
            )
        
        elif code_entity_search_result_model.action == "Next":
            return COMCodeEntitySearchEvent(
                manual=False,
                next=True,
            )
        
        elif code_entity_search_result_model.action == "End":
            # Return an orchestration event to continue the workflow
            return OrchestrationEvent(
                result_keys={
                    "Most Relevant Code Entity": code_entity_search_result_model.most_relevant_code_entity,
                    "Runner Up Code Entities": code_entity_search_result_model.runner_up_code_entities,
                }
            )
        
        else:
            raise ValueError(f"Unknown action: {code_entity_search_result_model.action}")

    @step
    async def com_root_module_search(self, ev: COMRootModuleSearchEvent) -> RootModuleSearchEvent:
        """
        Searches for root modules in the codebase using the COMStore.
        
        Args:
            ev (COMRootModuleSearchEvent): The event containing the input prompt for root module search.
        
        Returns:
            RootModuleSearchEvent: The event containing the next action to be taken in the workflow.
        """
        # Extract arguments from the event
        next = ev.next
        prompt = ev.prompt
        if not prompt and not next:
            raise ValueError("Either prompt or next must be provided.")
        
        root_modules = []
        if next:
            # Retrieve the next set of root modules from the COMStore
            root_modules = self.com_store.next_entities(
                from_="ROOT_MODULE",
                top_k=10
            )
            if not root_modules:
                raise ValueError("No more root modules found in the COMStore.")

            return RootModuleSearchEvent(
                manual=False,
                prompt=None,  # No prompt needed for next
                result_keys={
                    "Next Relevant Root Modules": root_modules["formatted_results"]
                }
            )
        else:
            # Search for root modules in the COMStore
            root_modules = self.com_store.retrieve_relevant_root_modules(
                query=prompt,
                top_k=10
            )
            if not root_modules:
                raise ValueError("No root modules found in the COMStore.")
            
            # Return a RootModuleSearchEvent with the found root modules
            return RootModuleSearchEvent(
                manual=False,
                prompt=None,  # No prompt needed for next
                result_keys={
                    "Relevant Root Modules": root_modules["formatted_results"]
                }
            )
        
    @step
    async def com_code_entity_search(self, ev: COMCodeEntitySearchEvent) -> CodeEntitySearchEvent:
        """
        Searches for code entities in the codebase using the COMStore.
        
        Args:
            ev (COMCodeEntitySearchEvent): The event containing the input prompt and parent module for code entity search.
        
        Returns:
            CodeEntitySearchEvent: The event containing the next action to be taken in the workflow.
        """
        # Extract arguments from the event
        next = ev.next
        prompt = ev.prompt
        parent = ev.parent
        if not prompt and not next:
            raise ValueError("Either prompt or next must be provided.")
        
        code_entities = []
        if next:
            # Retrieve the next set of code entities from the COMStore
            code_entities = self.com_store.next_entities(
                from_="CHILDREN",
                top_k=10
            )
            if not code_entities:
                raise ValueError("No more code entities found in the COMStore.")

            return CodeEntitySearchEvent(
                manual=False,
                prompt=None,  # No prompt needed for next
                root_module=parent,
                result_keys={
                    "Next Relevant Code Entities": code_entities["formatted_results"]
                }
            )
        else:
            # Search for code entities in the COMStore
            code_entities = self.com_store.retrieve_relevant_children_in_subtree(
                query=prompt,
                parent_name=parent,
                top_k=10
            )
            if not code_entities:
                raise ValueError("No code entities found in the COMStore.")
            
            # Return a CodeEntitySearchEvent with the found code entities
            return CodeEntitySearchEvent(
                manual=False,
                prompt=None,  # No prompt needed for next
                root_module=parent,
                result_keys={
                    "Relevant Code Entities": code_entities["formatted_results"]
                }
            )
        
    @step
    async def code_generation(self, ctx: Context, ev: CodeGenerationEvent) -> ReviewEvent | OrchestrationEvent:
        """
        Generates code based on the input prompt and relevant code entities.
        
        Args:
            ev (CodeGenerationEvent): The event containing the input prompt and relevant code entities for code generation.
        
        Returns:
            ReviewEvent | OrchestrationEvent: The event containing the next action to be taken in the workflow.
        """
        # Get the CGS memory from the context
        state = await ctx.get("state")
        if "cgs_memory" not in state:
            state["cgs_memory"] = Memory.from_defaults(
                token_limit=300000
            )
            # Put the system prompt in the CGS memory
            state["cgs_memory"].put(
                ChatMessage(
                    role="system",
                    content=CODE_GENERATION_PROMPT.format(
                        prompt=ev.prompt,
                        relevant_code_entities=", ".join(ev.relevant_code_entities)
                    )
                )
            )

        if ev.result_keys:
            # If the CodeGenerationEvent has result keys, add them to the CGS memory
            state["cgs_memory"].put(
                self.prepare_tool_message(ev.result_keys)
            )
        
        cgs_memory: Memory = state["cgs_memory"]
        chat_history = cgs_memory.get()

        # Use CodeGenerator to generate code
        code_generation_result = await BASE_LLM.achat(
            messages=chat_history,
        )

        code_generation_result_json = json.loads(code_generation_result.message.content)
        code_generation_result_model = CodeGenerationResult.model_validate_json(code_generation_result_json)

        # Append the code generation result to the CGS memory, and set the state
        cgs_memory.put(code_generation_result.message)
        state["cgs_memory"] = cgs_memory
        await ctx.set("state", state)

        # Decide next step based on the code generation result
        if not code_generation_result_model.code:
            raise ValueError("No code generated.")
        
        return ReviewEvent(
            manual=False,
            input=ev.prompt,
            result=code_generation_result_model.code,
            result_keys={
                "Generated Code": code_generation_result_model.code,
                "Brief Analysis": code_generation_result_model.brief_analysis,
            }
        )
