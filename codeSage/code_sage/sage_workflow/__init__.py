
from llama_index.core.tools import FunctionTool
from com_store import COMStore
from llama_index.core.agent.workflow import (
    AgentWorkflow,
    FunctionAgent,
)
from prompts import SEARCH_SYSTEM_PROMPT, CODE_SYSTEM_PROMPT

class SageWorkflow:
    def __init__(self, com_store: COMStore):
        self.com_store = com_store

    def create_necessary_tools(self):
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
        tools = {}
        tools['all_root_tools'] = [retrieve_root_modules_tool]
        tools['all_code_tools'] = [get_entity_info, get_full_path_name]
        tools['all_search_tools'] = [retrieve_children_tool]
        return tools
    def create_agents(self):
        tools = self.create_necessary_tools()
        root_agent = FunctionAgent(
            name="RootAgent",
            description="Agent that interacts with user primarily, uses tools to get an idea as to how the KG can help and then get relevant entites that can solve the query together",
            tools=tools['all_root_tools'],
            system_prompt=SEARCH_SYSTEM_PROMPT,
            can_handoff_to=["CodeAgent", "SearchAgent"]
        )

        code_agent = FunctionAgent(
            name="CodeAgent",
            description="Agent that generates code for a requested entity and a specific functionality that is to be satisfied by the generated code using the requested entity",
            tools=tools['all_code_tools'],
            system_prompt=CODE_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"]
        )
        search_agent = FunctionAgent(
            name="SearchAgent",
            description="Agent that explores and finds relevant code components based on user queries",
            tools=tools['all_search_tools'],
            system_prompt=SEARCH_SYSTEM_PROMPT,
            can_handoff_to=["RootAgent"]
        )
        return root_agent,[code_agent, search_agent]
    def create_agent_workflow(self):
        root_agent, agents = self.create_agents()
        agent_workflow = AgentWorkflow(
            agents=[root_agent] + agents,
            root_agent=root_agent.name
        )
        return agent_workflow