from llama_index.llms.google_genai import GoogleGenAI
from utils.prompts import CODE_GEN_PROMPT, TITLE_GEN_PROMPT
from utils.misc import stringify_scratchpad
from llama_index.core.workflow import Context
from config import config
import logging

code_gen_llm = GoogleGenAI(
    model="models/gemini-2.5-flash-preview-04-17",
    api_key=config.GEMINI_API_KEY,
    temperature=0.1,
)

title_gen_llm = GoogleGenAI(
    model="gemini-2.0-flash-lite",
    api_key=config.GEMINI_API_KEY,
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
        # Get the task for the code agent
        state = await ctx.get("state")
        task = state["task"]["code"]

        # Get the scratchpad as a string
        scratchpad_str = await stringify_scratchpad(ctx)
        
        # Generate code using the Gemini model
        response = await code_gen_llm.acomplete(
            CODE_GEN_PROMPT.format(
                agent_input=task,
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

async def write_task(ctx: Context, for_: str, task: str) -> str:
    """
    Generate a task for the given context and agent.

    Args:
        ctx (Context): The context object containing the scratchpad and other information.
        for_ (str): The agent for which the task is being generated.
        task (str): The descriptive and exhasutive content of the task, provided by the calling agent.

    Returns:
        str: Readable status explaining whether task was successfully set in the Context.
    """
    try:
        current_state = await ctx.get("state")

        if "task" not in current_state:
            current_state["task"] = {}

        current_state["task"][for_] = task
        await ctx.set("state", current_state)

        return "Task successfully set in the context."
    except Exception as e:
        logging.error(f"Error writing task: {e}")
        return "Error writing task."

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