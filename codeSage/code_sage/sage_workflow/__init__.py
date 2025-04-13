
from llama_index.core.tools import FunctionTool
from ..com_store import COMStore
from llama_index.core.agent.workflow import (
    AgentWorkflow,
    FunctionAgent,
)
from llama_index.core.agent.workflow import (
    AgentOutput,
    ToolCallResult,
    ToolCall,
)
from .agents.prompts import SEARCH_SYSTEM_PROMPT, CODE_SYSTEM_PROMPT, ROOT_SYSTEM_PROMPT
from .agents.com_agent import COMAgent
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SageWorkflow:
    def __init__(self, com_store: COMStore):
        self.com_store = com_store
        root_agent, agents = self.create_agents()
        self.root_agent = root_agent
        self.agents = agents
        self.agent_workflow = AgentWorkflow(
            agents=[root_agent] + agents,
            root_agent=root_agent.name
        )
        self.handler_ctx = None

    def create_necessary_tools(self):
        def next_top_k_root_modules(top_k: int = 10):
            return self.com_store.next_entities(from_="ROOT_MODULE", top_k=top_k)

        def next_top_k_children(top_k: int = 10):
            return self.com_store.next_entities(from_="CHILDREN", top_k=top_k)

        retrieve_root_modules_tool = FunctionTool.from_defaults(
            fn=self.com_store.retrieve_relevant_root_modules,
            description="Retrieve relevant root modules based on the query, using cosine similarity search"
        )
        retrieve_children_tool = FunctionTool.from_defaults(
            fn=self.com_store.retrieve_relevant_children_in_subtree,
            description="Retrieve relevant immediate children of the current node based on the query, using cosine similarity search"
        )
        get_entity_info = FunctionTool.from_defaults(
            fn=self.com_store.get_entity_info,
            description="""
            Get the information for the parent module of the entity from the code knowledge graph.
            Includes Name, Source Code, Summary, Imported Entities, Full Path and Shortest Call Path of the requested entity from it's root module.
            """
        )
        get_full_path_name = FunctionTool.from_defaults(
            fn=self.com_store.get_full_path_name,
            description="Get the full path name of the entity. Uses direct cypher query for deterministic response. If not found, uses Full-Text Search for Max Top 3 Matches."
        )
        get_next_top_k_root_modules = FunctionTool.from_defaults(
            fn=next_top_k_root_modules,
            description="""
            Get the next top k root modules. Use when you want the next set of root modules, from a previous call to `retrieve_root_modules_tool`.
            """
        )
        get_next_top_k_children = FunctionTool.from_defaults(
            fn=next_top_k_children,
            description="""
            Get the next top k children. Use when you want the next set of children, from a previous call to `retrieve_children_tool`.
            """
        )
        tools = {}
        tools["all_root_tools"] = [retrieve_root_modules_tool, get_next_top_k_root_modules]
        tools["all_code_tools"] = [get_entity_info, get_full_path_name]
        tools["all_search_tools"] = [retrieve_children_tool, get_next_top_k_children]
        return tools
    
    def create_agents(self):
        tools = self.create_necessary_tools()
        root_agent = FunctionAgent(
            name="RootAgent",
            description="Agent that interacts with user primarily, uses tools and interacts with other agents to get an idea as to how the KG can help and then get relevant entites that can solve the query together",
            tools=tools["all_root_tools"],
            system_prompt=ROOT_SYSTEM_PROMPT,
            can_handoff_to=["CodeAgent", "SearchAgent"]
        )

        code_agent = COMAgent(
            name="CodeAgent",
            description="Agent that generates code using requested entities for requested functionalities, after getting all of their important info using tools",
            tools=tools["all_code_tools"],
            system_prompt=CODE_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"],
            agent_type="code"
        )

        search_agent = COMAgent(
            name="SearchAgent",
            description="Agent that explores and finds relevant code components based on user queries",
            tools=tools["all_search_tools"],
            system_prompt=SEARCH_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"],
            agent_type="search"
        )

        return root_agent, [code_agent, search_agent]
    
    async def chat_with_agent_workflow(self, user_msg) -> str:
        """
        Handles the chat with the agent workflow.

        Args:
            user_msg (str): The message from the user.
        Returns:
            str: The response from the agent workflow.
        """
        try:
            handler = self.agent_workflow.run(
                ctx=self.handler_ctx,
                user_msg=user_msg
            )

            current_agent = None

            # TODO: Link required events to NVL (Neo4j Visualization Library)
            async for event in handler.stream_events():
                if (
                    hasattr(event, "current_agent_name")
                    and event.current_agent_name != current_agent
                ):
                    # TODO: Log the summaries generated by the agent handing off here
                    current_agent = event.current_agent_name
                    logger.info(f"🤖 Agent: {current_agent}")
                
                elif isinstance(event, AgentOutput):
                    if event.response.content:
                        logger.info("📤 Output: " + event.response.content)
                    if event.tool_calls:
                        logger.info(
                            "🛠️  Planning to use tools: " +
                            [call.tool_name for call in event.tool_calls],
                        )
                elif isinstance(event, ToolCallResult):
                    logger.info(f"🔧 Tool Result ({event.tool_name}):")
                    logger.info(f"  Arguments: {event.tool_kwargs}")
                    logger.info(f"  Output: {event.tool_output}")
                elif isinstance(event, ToolCall):
                    logger.info(f"🔨 Calling Tool: {event.tool_name}")
                    logger.info(f"  With arguments: {event.tool_kwargs}")

            self.handler_ctx = handler.ctx
            memory = await handler.ctx.get("memory")
            logger.info(f"Memory: {memory}")
            if not memory:
                raise ValueError("Memory is empty.")
            output = memory.get()[-1].content
            return output
        except Exception as e:
            logger.error(f"Error in chat_with_agent_workflow: {e}")
            return str(e)
        finally:
            pass

    