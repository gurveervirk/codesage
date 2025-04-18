from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (
    AgentWorkflow,
    FunctionAgent,
)
# TODO: Evaluate ChatMemoryBuffer in the future
from llama_index.core.memory import ChatSummaryMemoryBuffer
from llama_index.core.agent.workflow import (
    AgentOutput,
    ToolCallResult,
    ToolCall,
)
from llama_index.core.workflow import Context
from llama_index.core import Settings
from uuid import uuid4
from ..com_store import COMStore
from utils.prompts import SEARCH_SYSTEM_PROMPT, CODE_SYSTEM_PROMPT, ROOT_SYSTEM_PROMPT
from utils.code_gen import generate_code
from .agents.com_agent import COMAgent
from utils.title_gen import generate_title
import json
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper function to run a coroutine in the background and log errors
async def _run_and_log_errors(coro, task_name="Background task"):
    """Runs a coroutine and logs any exceptions."""
    try:
        await coro
    except Exception:
        logger.exception(f"{task_name} failed.")


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
        self.ctx = None
        self.chat_history = None
        self.ctx_index = self.load_contexts_index()
        self.reverse_ctx_index = {v: k for k, v in self.ctx_index.items()}
        self.ctx_id = None
        self.memory = None

    def load_contexts_index(self):
        """
        Loads the contexts index from the `contexts` directory.

        Args:
            None
        Returns:
            dict: A dictionary containing the context IDs and their corresponding titles.
        """
        try:
            # If the directory and the index file don't exist, create them
            if not os.path.exists("./contexts"):
                os.makedirs("./contexts")
            if not os.path.exists("./contexts/index.json"):
                with open("./contexts/index.json", "w") as f:
                    json.dump({}, f)

            ctx_index = {}
            
            # Load the index file
            with open("./contexts/index.json", "r") as f:
                ctx_index = json.load(f)

            # Check if the index is empty
            if not ctx_index:
                logger.info("Contexts index is empty.")
                return {}
            
            return ctx_index
        except FileNotFoundError:
            logger.warning("Contexts index file not found. Creating a new one.")
            return {}
        except json.JSONDecodeError:
            logger.error("Error decoding JSON from contexts index file. Creating a new one.")
            return {}

    def create_necessary_tools(self):
        def next_top_k_root_modules(top_k: int):
            return self.com_store.next_entities(from_="ROOT_MODULE", top_k=top_k)

        def next_top_k_children(top_k: int):
            return self.com_store.next_entities(from_="CHILDREN", top_k=top_k)

        retrieve_root_modules_tool = FunctionTool.from_defaults(
            fn=self.com_store.retrieve_relevant_root_modules,
            description="Retrieve relevant root modules based on the query, using cosine similarity search"
        )
        retrieve_children_tool = FunctionTool.from_defaults(
            fn=self.com_store.retrieve_relevant_children_in_subtree,
            description="Retrieve relevant immediate children of the current node based on the query, using cosine similarity search"
        )
        get_info_for_entities = FunctionTool.from_defaults(
            fn=self.com_store.get_info_for_entities,
            description="""
            Get the information for 1 or more entities.
            Includes Name, Full Path from it's root module, shortest call path from it's root module, signatures, summary by an LLM and it's docstring, if available, for each entity in a single string.
            """
        )
        get_full_path_names = FunctionTool.from_defaults(
            fn=self.com_store.get_full_path_names,
            description="Get the full path names of entities. Uses direct cypher query for deterministic response. If not found, uses Full-Text Search for Max Top 10 Matches, for each entity."
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
        generate_code_tool = FunctionTool.from_defaults(
            fn=generate_code,
            description="""
            Generate code using the requested entities for the requested functionality(ies).
            """
        )
        tools = {}
        tools["all_root_tools"] = [retrieve_root_modules_tool, get_next_top_k_root_modules]
        tools["all_code_tools"] = [get_info_for_entities, get_full_path_names, generate_code_tool]
        tools["all_search_tools"] = [retrieve_children_tool, get_next_top_k_children]
        return tools
    
    def create_agents(self):
        tools = self.create_necessary_tools()
        root_agent = FunctionAgent(
            name="RootAgent",
            description="RootAgent: Agent that interacts with user primarily, uses tools and interacts with other agents to get an idea as to how the KG can help and then get relevant entites that can solve the query together",
            tools=tools["all_root_tools"],
            system_prompt=ROOT_SYSTEM_PROMPT,
            can_handoff_to=["CodeAgent", "SearchAgent"]
        )

        code_agent = COMAgent(
            name="CodeAgent",
            description="CodeAgent: Agent that generates code using requested entities for requested functionalities, after getting all of their important info using tools",
            tools=tools["all_code_tools"],
            system_prompt=CODE_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"],
            agent_type="code"
        )

        search_agent = COMAgent(
            name="SearchAgent",
            description="SearchAgent: Agent that explores and finds relevant code components based on user queries",
            tools=tools["all_search_tools"],
            system_prompt=SEARCH_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"],
            agent_type="search"
        )

        return root_agent, [code_agent, search_agent]
    
    def update_title(self, ctx_id: str, title: str):
        """
        Updates the title of the context in the `contexts` directory.

        Args:
            ctx_id (str): The ID of the context to update.
            title (str): The new title for the context.
        Returns:
            None
        """
        try:
            if ctx_id not in self.reverse_ctx_index:
                raise ValueError(f"Context with id {ctx_id} not found.")
            
            # Update the index with the new title
            self.reverse_ctx_index[title] = ctx_id

            # Remove the old title from the index
            old_title = self.ctx_index[ctx_id]
            if old_title in self.reverse_ctx_index:
                del self.reverse_ctx_index[old_title]

            self.ctx_index[ctx_id] = title
            
            # Save the updated index to the file
            with open("./contexts/index.json", "w") as f:
                json.dump(self.ctx_index, f)
            
            logger.info(f"Title updated successfully: {title}")
        except Exception as e:
            logger.error(f"Error updating title: {e}")
            raise e
    
    async def update_stored_context(self):
        """
        Updates the stored context in the `contexts` directory.
        Generates a title if it's a new context.
        """
        try:
            if self.ctx is None:
                raise ValueError("Handler context is not set. Cannot update stored context.")
            
            if self.ctx_id is None:
                # Generate title and update index, using the chat history
                title = await generate_title(self.chat_history)
                self.ctx_id = str(uuid4())
                self.reverse_ctx_index[title] = self.ctx_id
                self.ctx_index[self.ctx_id] = title
                with open("./contexts/index.json", "w") as f:
                    json.dump(self.ctx_index, f)
                logger.info(f"Title generated: {title}")

            elif self.ctx_index[self.ctx_id] is None:
                # Generate title and update index
                title = await generate_title(self.chat_history)
                self.reverse_ctx_index[title] = self.ctx_id
                self.ctx_index[self.ctx_id] = title
                with open("./contexts/index.json", "w") as f:
                    json.dump(self.ctx_index, f)
                logger.info(f"Title generated: {title}")
            
            context = self.ctx.to_dict()
            
            # Create the directory if it doesn't exist
            context_dir = f"./contexts/{self.ctx_id}"
            os.makedirs(context_dir, exist_ok=True)

            # Save the context to a single JSON file
            with open(f"{context_dir}/ctx.json", "w") as f:
                json.dump(context, f)

            # Save the chat history to a separate JSON file
            with open(f"{context_dir}/chat_history.json", "w") as f:
                json.dump(self.chat_history, f)
            
            logger.info(f"Context updated successfully: {self.ctx_id}")
        except Exception as e:
            logger.error(f"Error updating context: {e}")
            raise e
    
    async def chat_with_agent_workflow(self, user_msg) -> str:
        """
        Handles the chat with the agent workflow.

        Args:
            user_msg (str): The message from the user.
        Returns:
            str: The response from the agent workflow.
        """
        try:
            # Create a new memory buffer for the chat, if not already set
            if self.memory is None:
                self.memory = ChatSummaryMemoryBuffer.from_defaults(
                    llm=Settings.llm,
                )

            # Add the user message to the chat history
            if self.chat_history is None:
                self.chat_history = []
            
            self.chat_history.append(user_msg)

            handler = self.agent_workflow.run(
                ctx=self.ctx,
                memory=self.memory,
                user_msg=user_msg
            )
            logger.info(f"User: {user_msg}")

            current_agent = None
            final_response = None

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
                        final_response = event.response.content
                    if event.tool_calls:
                        logger.info(
                            "🛠️  Planning to use tools: " +
                            ", ".join([call.tool_name for call in event.tool_calls])
                        )
                elif isinstance(event, ToolCallResult):
                    logger.info(f"🔧 Tool Result ({event.tool_name}):")
                    logger.info(f"  Arguments: {event.tool_kwargs}")
                    logger.info(f"  Output: {event.tool_output}")
                elif isinstance(event, ToolCall):
                    logger.info(f"🔨 Calling Tool: {event.tool_name}")
                    logger.info(f"  With arguments: {event.tool_kwargs}")

            if final_response is None:
                final_response = "No response generated."
                return final_response

            # Set latest ctx to ctx
            self.ctx = handler.ctx

            # Append the final response to the chat history
            self.chat_history.append(final_response)

            # Schedule the context update to run in the background and log errors
            # Shield the task to prevent cancellation if the main chat task is cancelled
            update_coro = self.update_stored_context()
            asyncio.create_task(_run_and_log_errors(asyncio.shield(update_coro), "Context Update"))

            return final_response
        except Exception as e:
            logger.error(f"Error in chat_with_agent_workflow: {e}")
            return str(e)
        finally:
            pass

    async def reset_context(self):
        """
        Resets the chat context and agent workflow.
        """
        # If the context is not None, save it to the context file
        if self.ctx is not None:
            try:
                # # Get the memories and store them
                # memories = await self.get_memories()
                context = self.ctx.to_dict()
                with open(f"contexts/{self.ctx_id}/ctx.json", "w") as f:
                    json.dump(context, f)

                with open(f"contexts/{self.ctx_id}/chat_history.json", "w") as f:
                    json.dump(self.chat_history, f)
            except Exception as e:
                logger.error(f"Error saving context: {e}")

        self.ctx = None
        self.ctx_id = None
        self.memory = None
        self.chat_history = None

    async def load_context(self, id: str) -> list[str]:
        """
        Loads the context for the agent workflow, from `contexts` directory.

        Args:
            ctx: The context to load.
        Returns:
            list[str]: A list of strings representing the chat history.
        """
        try:
            if id not in self.ctx_index:
                raise ValueError(f"Context with id {id} not found.")
            context = json.load(open(f"./contexts/{id}/ctx.json", "r"))
            self.chat_history = json.load(open(f"./contexts/{id}/chat_history.json", "r"))

            # Create a new context
            self.ctx = Context.from_dict(
                workflow=self.agent_workflow,
                data=context,
            )

            self.memory = await self.ctx.get("memory", default=None)
            self.ctx_id = id
            logger.info(f"Context loaded successfully: {self.ctx_id}")

            return self.chat_history
            
        except Exception as e:
            logger.error(f"Error loading context: {e}")
            raise e
        
    def delete_context(self, id: str):
        """
        Deletes the context from the `contexts` directory.

        Args:
            ctx: The context to delete.
        Returns:
            None
        """
        try:
            if id not in self.ctx_index:
                raise ValueError(f"Context with id {id} not found.")
            
            # Delete the context files and directory
            os.remove(f"./contexts/{id}/ctx.json")
            os.remove(f"./contexts/{id}/chat_history.json")
            os.rmdir(f"./contexts/{id}")
            
            # Remove the context from the index
            del self.reverse_ctx_index[self.ctx_index[id]]
            del self.ctx_index[id]
            
            # Save the updated index to the file
            with open("./contexts/index.json", "w") as f:
                json.dump(self.ctx_index, f)
            
            logger.info(f"Context deleted successfully: {id}")
        except Exception as e:
            logger.error(f"Error deleting context: {e}")
            raise e
        
    # TODO: Add rerun message function in the future