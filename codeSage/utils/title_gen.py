from utils.gemini_with_rate_limits import GeminiWithRateLimits
from utils.prompts import TITLE_GEN_PROMPT
import logging

title_gen_llm = GeminiWithRateLimits(
    model="models/gemini-2.0-flash-lite",
    temperature=0.1,
)

async def generate_title(chat: list[str]) -> str:
    """
    Generate a title for the given chat using the LLM.

    Args:
        chat (list[str]): The chat history as a list of strings.
        
    Returns:
        str: The generated title.
    """

    try:
        # Format the chat history for the prompt
        chat = "\n".join([
            f"User: {message}" if i % 2 == 0 else f"AI: {message}"
            for i, message in enumerate(chat)
        ])
        prompt = TITLE_GEN_PROMPT.format(chat=chat)

        # Generate the title using the LLM
        title = await title_gen_llm.acomplete(
            prompt=prompt,
        )

        title = title.text.strip()

        # Extract the title from the response
        if title.startswith("<title>") and title.endswith("</title>"):
            title = title[7:-8].strip()
        else:
            raise ValueError("Invalid title format.")
        
        return None if title == "NONE" else title
    except Exception as e:
        logging.info(f"Error generating title: {e}")
        return None