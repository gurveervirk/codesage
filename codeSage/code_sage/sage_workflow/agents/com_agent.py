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
from .prompts import SUMMARIZE_CODE_SCRATCHPAD_PROMPT, SUMMARIZE_SEARCH_SCRATCHPAD_PROMPT

class COMAgent(FunctionAgent):
    """Custom COM agent implementation."""

    current_agent_input_key: str = "current_agent_input"
    agent_type: Union[Literal['code'], Literal['search']] = Field(
        description =" The type of the agent. ACCEPTED VALUES: 'code', 'search'",
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
    def _token_count_for_messages(self, messages: List[ChatMessage]) -> int:
        if len(messages) <= 0:
            return 0

        msg_str = " ".join(str(m.content) for m in messages)
        return len(self.tokenizer_fn(msg_str))

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
        mem_key: str = self.agent_type + "_mem"
        com_mem: List[ChatMessage] = await ctx.get(mem_key, default=[])
        current_agent_input: ChatMessage = await ctx.get(
            self.current_agent_input_key, default=None
        )

        # If the current agent input is None, set it to the last input in the input list (as that would be the input to this agent)
        if current_agent_input is None:
            await ctx.set(self.current_agent_input_key, llm_input[-1])
            current_agent_input = llm_input[-1]

        # Prepare the input for the LLM, including only the code memory of this agent, the input to this agent, and it's temporary scratchpad
        current_llm_input = [*com_mem, current_agent_input, *scratchpad]

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

        Summarizes the current scratchpad in detail and appends to the Code Agent's memory.
        """
        scratchpad: List[ChatMessage] = await ctx.get(self.scratchpad_key, default=[])
        mem_key: str = self.agent_type + "_mem"
        com_mem: List[ChatMessage] = await ctx.get(mem_key, default=[])
        current_agent_input: str = await ctx.get(
            self.current_agent_input_key, default=None
        )

        # Summarize the scratchpad into a single message using the LLM
        scratchpad_str = "\n\n".join([m.content for m in scratchpad])
        PROMPT = self.code_summarize_prompt if self.agent_type == "code" else self.search_summarize_prompt
        response = await self.llm.acomplete(
            f"{PROMPT.format(current_agent_input=current_agent_input, scratchpad=scratchpad_str)}"
        )

        # Append the summarized message to the memory
        summary_message = ChatMessage(role="assistant", content=response.text)
        com_mem.append(summary_message)
        await memory.aput(summary_message)

        # If the agent's memory is too large, remove the oldest messages, then update the memory of this agent
        message_count = len(com_mem)
        token_count = self._token_count_for_messages(com_mem)

        while token_count > self.max_mem_token_limit and message_count > 1:
            message_count -= 1
            com_mem.pop(0)
            token_count = self._token_count_for_messages(com_mem)

        if token_count > self.max_mem_token_limit or message_count <= 0:
            com_mem = []

        await ctx.set(mem_key, com_mem)

        # Reset current agent input
        await ctx.set(self.current_agent_input_key, None)

        # reset scratchpad
        await ctx.set(self.scratchpad_key, [])

        return output