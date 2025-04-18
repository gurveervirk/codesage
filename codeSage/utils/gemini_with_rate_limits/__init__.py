from typing import (
    Any,
    Dict,
    AsyncGenerator,
    List,
    Optional,
    Sequence,
    Union,
)
from llama_index.llms.gemini.utils import (
    chat_from_gemini_response,
    chat_message_to_gemini,
    completion_from_gemini_response,
)
from llama_index.llms.gemini import Gemini
from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    CompletionResponse,
    CompletionResponseAsyncGen,
)
from llama_index.core.bridge.pydantic import (
    BaseModel,
    Field,
)
from llama_index.core.types import Model
from llama_index.core.llms.callbacks import llm_chat_callback, llm_completion_callback
import llama_index.core.instrumentation as instrument
from aiolimiter import AsyncLimiter
from tenacity import retry, stop_after_attempt, wait_incrementing

dispatcher = instrument.get_dispatcher(__name__)

GEMINI_MODELS = (
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-lite",
    "models/gemini-2.0-flash-thinking",
    "models/gemini-2.0-flash-thinking-exp-01-21",
    "models/gemini-2.0-flash-lite-preview-02-05",
    "models/gemini-2.0-pro-exp-02-05",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-8b",
    "models/gemini-1.0-pro",
)
from llama_index.core.utilities.gemini_utils import (
    merge_neighboring_same_role_messages,
)

# Define retry strategy: wait 5s, then 10s, stop after 3 attempts total
retry_strategy = retry(
    stop=stop_after_attempt(3),
    wait=wait_incrementing(start=5, increment=5),
)

class GeminiWithRateLimits(Gemini):
    rate_limit: int = Field(
        default=15,
        description="The number of allowed calls per period."
    )
    period: int = Field(
        default=60,
        description="The period in seconds for the rate limit."
    )
    limiter: AsyncLimiter = Field(
        default=None,
        exclude=True,
        description="The async rate limiter instance."
    )
    def __init__(
        self,
        model: str = GEMINI_MODELS[0],
        rate_limit: Optional[int] = 15,  # Default rate limit
        period: Optional[int] = 60,  # Default period
        **kwargs: Any,
    ):
        """Creates a new Gemini model interface."""
        super().__init__(
            model=model,
            **kwargs,
        )
        self.rate_limit = rate_limit
        self.period = period
        self.limiter = AsyncLimiter(self.rate_limit, self.period)

    @llm_chat_callback()
    @retry_strategy
    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        request_options = self._request_options or kwargs.pop("request_options", None)
        merged_messages = merge_neighboring_same_role_messages(messages)
        *history, next_msg = map(chat_message_to_gemini, merged_messages)
        chat = self._model.start_chat(history=history)

        async with self.limiter:
            response = await chat.send_message_async(
                next_msg, request_options=request_options, **kwargs
            )
            return chat_from_gemini_response(response)

    @llm_completion_callback()
    @retry_strategy
    async def acomplete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        request_options = self._request_options or kwargs.pop("request_options", None)
        async with self.limiter:
            result = await self._model.generate_content_async(
                prompt, request_options=request_options, **kwargs
            )
            return completion_from_gemini_response(result)

    @llm_completion_callback()
    @retry_strategy
    def astream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseAsyncGen:
        request_options = self._request_options or kwargs.pop("request_options", None)

        async def gen():
            async with self.limiter:
              it = await self._model.generate_content_async(
                  prompt, stream=True, request_options=request_options, **kwargs
              )
              async for r in it:
                  yield completion_from_gemini_response(r)

        return gen()

    @llm_chat_callback()
    @retry_strategy
    async def astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseAsyncGen:
        request_options = self._request_options or kwargs.pop("request_options", None)
        merged_messages = merge_neighboring_same_role_messages(messages)
        *history, next_msg = map(chat_message_to_gemini, merged_messages)
        chat = self._model.start_chat(history=history)
        async with self.limiter:
          response = await chat.send_message_async(
              next_msg, stream=True, request_options=request_options, **kwargs
          )

          async def gen() -> ChatResponseAsyncGen:
              content = ""
              existing_tool_calls = []
              async for r in response:
                  top_candidate = r.candidates[0]
                  content_delta = top_candidate.content.parts[0].text
                  content += content_delta
                  llama_resp = chat_from_gemini_response(r)
                  existing_tool_calls.extend(
                      llama_resp.message.additional_kwargs.get("tool_calls", [])
                  )
                  llama_resp.delta = content_delta
                  llama_resp.message.content = content
                  llama_resp.message.additional_kwargs["tool_calls"] = existing_tool_calls
                  yield llama_resp

          return gen()

    @dispatcher.span
    @retry_strategy
    async def astructured_predict(
        self, *args: Any, llm_kwargs: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> BaseModel:
        """Structured predict."""
        llm_kwargs = llm_kwargs or {}
        all_kwargs = {**llm_kwargs, **kwargs}

        if self._is_function_call_model:
            llm_kwargs["tool_choice"] = (
                "required"
                if "tool_choice" not in all_kwargs
                else all_kwargs["tool_choice"]
            )
        # by default structured prediction uses function calling to extract structured outputs
        # here we force tool_choice to be required
        async with self.limiter:
          return await super().astructured_predict(*args, llm_kwargs=llm_kwargs, **kwargs)

    @dispatcher.span
    @retry_strategy
    async def astream_structured_predict(
        self, *args: Any, llm_kwargs: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> AsyncGenerator[Union[Model, List[Model]], None]:
        """Stream structured predict."""
        llm_kwargs = llm_kwargs or {}
        all_kwargs = {**llm_kwargs, **kwargs}

        if self._is_function_call_model:
            llm_kwargs["tool_choice"] = (
                "required"
                if "tool_choice" not in all_kwargs
                else all_kwargs["tool_choice"]
            )
        # by default structured prediction uses function calling to extract structured outputs
        # here we force tool_choice to be required
        async with self.limiter:
          async for item in await super().astream_structured_predict(
              *args, llm_kwargs=llm_kwargs, **kwargs
          ):
              yield item