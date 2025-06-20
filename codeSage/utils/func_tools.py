from llama_index.llms.google_genai import GoogleGenAI
from utils.prompts import CODE_GEN_PROMPT, CODE_REVIEW_PROMPT, TITLE_GEN_PROMPT
from utils.misc import stringify_scratchpad
from utils.models import CodeReview
from llama_index.core.workflow import Context
from config import config
from typing import Any
import json
import logging

code_gen_llm = GoogleGenAI(
    model="gemini-2.5-flash-preview-04-17",
    api_key=config.GEMINI_API_KEY,
    temperature=0.1,
)

code_review_llm = code_gen_llm.as_structured_llm(CodeReview)

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

        # Initialize additional_instructions to None
        additional_instructions = None

        # Loop through code gen and code review until we have a valid response
        while True:
            # Generate code using the Gemini model
            response = await code_gen_llm.acomplete(
                CODE_GEN_PROMPT.format(
                    agent_input=task,
                    scratchpad=scratchpad_str,
                    additional_instructions=additional_instructions if additional_instructions else "NONE",
                )
            )
            
            # Extract the text from the response
            generated_content = response.text if hasattr(response, "text") else str(response)

            logging.info(f"Generated code: {generated_content}")

            # Review the generated content using the LLM
            prompt = CODE_REVIEW_PROMPT.format(
                agent_input=task,
                scratchpad=scratchpad_str,
                code_snippet=generated_content
            )

            review_response = await code_review_llm.acomplete(
                prompt=prompt,
            )

            logging.info(f"Review response: {review_response.text}")

            # Load the review response as a CodeReview object
            code_review = CodeReview.model_validate_json(review_response.text)
            review = code_review.review
            correctness = code_review.correctness
            functionality = code_review.functionality
            best_practices = code_review.best_practices
            error_handling = code_review.error_handling
            incorrect_usage_entities = code_review.incorrect_usage_entities
            missing_info_entities = code_review.missing_info_entities

            # Check the review response
            if correctness and functionality and best_practices and error_handling and not missing_info_entities and not incorrect_usage_entities:
                break  # If the code is correct, functional, follows best practices, has error handling, and no missing or incorrect entities, break the loop

            if missing_info_entities:
                # Format final response with missing entities
                final_response = {
                    "review": review,
                    "missing_info_entities": missing_info_entities,
                }

                return json.dumps(final_response, indent=2)
            
            # If the code is not correct, functional, or has issues, update additional instructions
            additional_instructions = (
                f"Review: {review}\n"
                f"Correctness: {"Satisfactory" if correctness else "Unsatisfactory"}\n"
                f"Functionality: {"Satisfactory" if functionality else "Unsatisfactory"}\n"
                f"Best Practices: {"Satisfactory" if best_practices else "Unsatisfactory"}\n"
                f"Error Handling: {"Satisfactory" if error_handling else "Unsatisfactory"}\n"
                f"Incorrect Usage Entities: {', '.join(incorrect_usage_entities) if incorrect_usage_entities else 'None'}\n"
            )
        
        response = {}
        # Extract blocks from the generated content
        if "<code>" in generated_content and "</code>" in generated_content:
            start = generated_content.index("<code>") + len("<code>")
            end = generated_content.index("</code>")
            response["code"] = generated_content[start:end].strip()
        else:
            logging.warning("No <code> blocks found in the generated content.")

        if "<reasoning>" in generated_content and "</reasoning>" in generated_content:
            start = generated_content.index("<reasoning>") + len("<reasoning>")
            end = generated_content.index("</reasoning>")
            response["reasoning"] = generated_content[start:end].strip()
        else:
            logging.warning("No <reasoning> blocks found in the generated content.")

        if "<entities_with_missing_info>" in generated_content and "</entities_with_missing_info>" in generated_content:
            start = generated_content.index("<entities_with_missing_info>") + len("<entities_with_missing_info>")
            end = generated_content.index("</entities_with_missing_info>")
            response["entities_with_missing_info"] = generated_content[start:end].strip()
        
        else:
            logging.warning("No <entities_with_missing_info> blocks found in the generated content.")

        # Store the response in the context state
        state["code_gen"] = response
        await ctx.set("state", state)

        # Return the generated content
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

        return "Task successfully set in the context. Please handoff to the appropriate agent."
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
   