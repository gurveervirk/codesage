from typing import (
    Union,
    List,
    Any,
    Dict,
    Generator,
    Optional,
    Sequence,
)
from llama_index.core.types import Model
from llama_index.llms.gemini.utils import (
    chat_from_gemini_response,
    chat_message_to_gemini,
    completion_from_gemini_response,
)
from llama_index.llms.gemini import Gemini
from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    CompletionResponse
)
from llama_index.core.bridge.pydantic import Field
from llama_index.core.constants import DEFAULT_TEMPERATURE
from llama_index.core.callbacks import CallbackManager
from llama_index.core.bridge.pydantic import (
    BaseModel,
    Field,
)
from aiolimiter import AsyncLimiter
import google.generativeai as genai
import llama_index.core.instrumentation as instrument

dispatcher = instrument.get_dispatcher(__name__)

GEMINI_MODELS = (
    "models/gemini-2.0-flash-001",
    "models/gemini-2.0-flash-exp",
    # Gemini 1.0 Pro Vision has been deprecated on July 12, 2024.
    # According to official recommendations, switch the default model to gemini-1.5-flash
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-latest",
    "models/gemini-pro",
    "models/gemini-pro-latest",
    "models/gemini-1.5-pro",
    "models/gemini-1.5-pro-latest",
    "models/gemini-1.0-pro",
    # for some reason, google lists this without the models prefix
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.0-pro",
)
from llama_index.core.utilities.gemini_utils import (
    merge_neighboring_same_role_messages,
)
from llama_index.llms.gemini import Gemini

class GeminiWithRateLimits(Gemini):
    rate_limit: int = Field(
        default=10,
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
        api_key: Optional[str] = None,
        model: str = GEMINI_MODELS[0],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: Optional[int] = None,
        generation_config: Optional[genai.types.GenerationConfigDict] = None,
        safety_settings: Optional[genai.types.SafetySettingDict] = None,
        callback_manager: Optional[CallbackManager] = None,
        api_base: Optional[str] = None,
        transport: Optional[str] = None,
        model_name: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        request_options: Optional[genai.types.RequestOptions] = None,
        rate_limit: Optional[int] = 10,  # Default rate limit
        period: Optional[int] = 60,  # Default period
        **generate_kwargs: Any,
    ):
        """Creates a new Gemini model interface."""
        super().__init__(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            generation_config=generation_config,
            safety_settings=safety_settings,
            callback_manager=callback_manager,
            api_base=api_base,
            transport=transport,
            model_name=model_name,
            default_headers=default_headers,
            request_options=request_options,
            **generate_kwargs,
        )
        self.rate_limit = rate_limit
        self.period = period
        self.limiter = AsyncLimiter(self.rate_limit, self.period)

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

    async def acomplete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        request_options = self._request_options or kwargs.pop("request_options", None)
        async with self.limiter:
            result = await self._model.generate_content_async(
                prompt, request_options=request_options, **kwargs
            )
            return completion_from_gemini_response(result)

    @dispatcher.span
    async def astructured_predict(
        self, *args: Any, llm_kwargs: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> BaseModel:
        """Structured predict."""
        llm_kwargs = llm_kwargs or {}
        all_kwargs = {**llm_kwargs, **kwargs}

        llm_kwargs["tool_choice"] = (
            "required" if "tool_choice" not in all_kwargs else all_kwargs["tool_choice"]
        )
        # by default structured prediction uses function calling to extract structured outputs
        # here we force tool_choice to be required

        async with self.limiter:
            return await super().astructured_predict(*args, llm_kwargs=llm_kwargs, **kwargs)

    @dispatcher.span
    async def astream_structured_predict(
        self, *args: Any, llm_kwargs: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Generator[Union[Model, List[Model]], None, None]:
        """Stream structured predict."""
        llm_kwargs = llm_kwargs or {}
        all_kwargs = {**llm_kwargs, **kwargs}

        llm_kwargs["tool_choice"] = (
            "required" if "tool_choice" not in all_kwargs else all_kwargs["tool_choice"]
        )
        # by default structured prediction uses function calling to extract structured outputs
        # here we force tool_choice to be required
        async with self.limiter:
            return await super().astream_structured_predict(
                *args, llm_kwargs=llm_kwargs, **kwargs
            )