from utils.gemini_with_rate_limits import GeminiWithRateLimits
from utils.prompts import CODE_GEN_PROMPT
from llama_index.core.workflow import Context
from llama_index.core.llms import ChatMessage
import logging

code_gen_llm = GeminiWithRateLimits(
    model="models/gemini-2.0-flash-lite",
    temperature=0.1,
)

async def generate_code(ctx: Context) -> str:
    """
    Generate code based on information about code entities (functions, classes, methods).
    
    Args:
        ctx (Context): The context object containing information about code entities in the scratchpad.
        
    Returns:
        str: Generated code with reasoning, formatted in markdown.
    """
    try:
        # Get the chat history from the context
        scratchpad: list[ChatMessage] = await ctx.get("scratchpad", default=[])
        agent_input: str = await ctx.get("current_agent_input", default="")

        # Get the chat history as a string
        scratchpad_str = ""

        for message in scratchpad:
            message_str = f"{message.role}: "
            if message.content is not None:
                message_str += message.content
            else:
                message_str += "No content, presumably tool usage."
            scratchpad_str += message_str + "\n\n"
        
        # Generate code using the Gemini model
        response = await code_gen_llm.acomplete(
            CODE_GEN_PROMPT.format(
                agent_input=agent_input,
                scratchpad=scratchpad_str
            )
        )
        
        # Extract the text from the response
        generated_content = response.text if hasattr(response, "text") else str(response)
        
        # Return the formatted response
        return generated_content

    except Exception as e:
        logging.error(f"Error generating code: {e}")
        return f"Error generating code: {e}"