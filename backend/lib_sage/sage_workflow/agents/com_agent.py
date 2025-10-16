from llama_index.core.agent.workflow import FunctionAgent
from typing import List, Sequence, Union, Literal, Callable
from llama_index.core.agent.workflow.workflow_events import (
    AgentInput,
    AgentOutput,
    AgentStream,
)
from llama_index.core.bridge.pydantic import (
    BaseModel,
    Field,
)
from llama_index.core.llms import ChatMessage
from llama_index.core.memory import BaseMemory
from llama_index.core.tools import AsyncBaseTool
from llama_index.core.workflow import Context
from llama_index.core.utils import get_tokenizer
from backend.utils.prompts import (
    SUMMARIZE_CODE_SCRATCHPAD_PROMPT,
    SUMMARIZE_SEARCH_SCRATCHPAD_PROMPT,
)
from backend.utils.misc import stringify_scratchpad

class COMAgent(FunctionAgent):
    """Custom COM agent implementation."""

    agent_type: Union[Literal['code'], Literal['search']] = Field(
        description =" The type of the agent. ACCEPTED VALUES: 'code', 'search'",
        default = None
    )
    memory: list = Field(
        description = "The memory of the agent, comprised of the summaries of past tasks",
        default = None
    )
    code_summarize_prompt: str = Field(
        description = "The prompt to summarize the code scratchpad",
        default = SUMMARIZE_CODE_SCRATCHPAD_PROMPT
    )
    search_summarize_prompt: str = Field(
        description = "The prompt to summarize the search scratchpad",
        default = SUMMARIZE_SEARCH_SCRATCHPAD_PROMPT
    )
    max_mem_token_limit: int = Field(
        description = "The maximum number of tokens to store in memory",
        default = 100000
    )
    tokenizer_fn: Callable[[str], List] = Field(
        default_factory=get_tokenizer,
        exclude=True,
    )

    # Picked from llama_index.core.memory.chat_memory_buffer
    def _token_count_for_messages(self, messages: list[str]) -> int:
        if len(messages) <= 0:
            return 0

        msg_str = "\n\n".join(messages)
        return len(self.tokenizer_fn(msg_str))
    
    async def _prepare_system_prompt(self, ctx: Context, system_prompt: ChatMessage) -> ChatMessage:
        """
        Prepare the system prompt for the agent.

        Args:
            ctx (Context): The context object containing the scratchpad, and other information.
            system_prompt (ChatMessage): The system prompt to prepare.

        Returns:
            ChatMessage: The prepared system prompt.
        """
        prepared_sys_prompt_content = system_prompt.content

        if self.memory is not None:
            prepared_sys_prompt_content += f"\n\n# Summaries of past tasks:\n\n{'\n\n'.join(self.memory)}"

        state = await ctx.get("state")
        task = state["task"][self.agent_type]

        if task is not None:
            prepared_sys_prompt_content += f"\n\n## Current task:\n\n{task}"

        prepared_sys_prompt = ChatMessage(
            role=system_prompt.role,
            content=prepared_sys_prompt_content,
        )

        return prepared_sys_prompt
    
    def _update_memory(self, text: str) -> None:
        """
        Update the memory of the agent.

        Args:
            text (str): The text to update the memory with.
        """
        if self.memory is None:
            self.memory = []

        self.memory.append(text)

        # If the agent's memory is too large, remove the oldest messages, then update the memory of this agent
        message_count = len(self.memory)
        token_count = self._token_count_for_messages(self.memory)

        while token_count > self.max_mem_token_limit and message_count > 1:
            message_count -= 1
            self.memory.pop(0)
            token_count = self._token_count_for_messages(self.memory)

        if token_count > self.max_mem_token_limit or message_count <= 0:
            self.memory = []

    async def take_step(
        self,
        ctx: Context,
        llm_input: List[ChatMessage],
        tools: Sequence[AsyncBaseTool],
        memory: BaseMemory = None,
    ) -> AgentOutput:
        """Take a single step with the function calling agent."""
        if not self.llm.metadata.is_function_calling_model:
            raise ValueError("LLM must be a FunctionCallingLLM")

        scratchpad: List[ChatMessage] = await ctx.get(self.scratchpad_key, default=[])
        system_prompt = llm_input[0]

        # Prepare the system prompt with memory and current task
        system_prompt = await self._prepare_system_prompt(ctx, system_prompt)

        # Prepare the input for the LLM, including the system prompt with memory, the input to this agent, and it's temporary scratchpad
        current_llm_input = [system_prompt, *scratchpad]

        ctx.write_event_to_stream(
            AgentInput(input=current_llm_input, current_agent_name=self.name)
        )

        response = await self.llm.astream_chat_with_tools(  # type: ignore
            tools, chat_history=current_llm_input, allow_parallel_tool_calls=True
        )
        async for r in response:
            tool_calls = self.llm.get_tool_calls_from_response(  # type: ignore
                r, error_on_no_tool_call=False
            )
            raw = r.raw.model_dump() if isinstance(r.raw, BaseModel) else r.raw
            ctx.write_event_to_stream(
                AgentStream(
                    delta=r.delta or "",
                    response=r.message.content or "",
                    tool_calls=tool_calls or [],
                    raw=raw,
                    current_agent_name=self.name,
                )
            )

        tool_calls = self.llm.get_tool_calls_from_response(  # type: ignore
            r, error_on_no_tool_call=False
        )

        # only add to scratchpad if we didn't select the handoff tool
        scratchpad.append(r.message)
        await ctx.set(self.scratchpad_key, scratchpad)

        raw = r.raw.model_dump() if isinstance(r.raw, BaseModel) else r.raw
        return AgentOutput(
            response=r.message,
            tool_calls=tool_calls or [],
            raw=raw,
            current_agent_name=self.name,
        )

    async def finalize(
        self, ctx: Context, output: AgentOutput, memory: BaseMemory
    ) -> AgentOutput:
        """Finalize the function calling agent.

        Summarizes the current scratchpad in detail and appends to the COM Agent's memory.
        """
        state = await ctx.get("state")
        task = state["task"][self.agent_type]

        # Get the scratchpad as a string
        scratchpad_str = await stringify_scratchpad(ctx)

        if self.agent_type == "code":
            # Get reasoning and code from state
            code_gen = state.get("code_gen", {})
            reasoning = code_gen.get("reasoning", "")
            code = code_gen.get("code", "")
            if not reasoning and not code:
                raise ValueError("No reasoning or code found in state for code agent.")
            
            # Format response
            response = f"## Reasoning:\n\n{reasoning}\n\n## Code:\n\n{code}"

        else:
            PROMPT = self.search_summarize_prompt
            response = await self.llm.acomplete(
                f"{PROMPT.format(current_agent_input=task, scratchpad=scratchpad_str)}"
            )
            response = response.text.strip()

        # Append the summarized message to the memory for the root agent and this agent
        summary_message = ChatMessage(role="assistant", content=response)
        await memory.aput(summary_message)
        self._update_memory(response)

        # Append a handoff message to the memory for the root agent
        handoff_message = ChatMessage(role='tool', content='I have provided a summary of my work. Handing off to Root Agent. Please proceed.')
        await memory.aput(handoff_message)

        # Reset the task for this agent
        state["task"][self.agent_type] = None
        await ctx.set("state", state)

        # reset scratchpad
        await ctx.set(self.scratchpad_key, [])

        return output