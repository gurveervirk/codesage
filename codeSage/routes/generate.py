from fastapi import APIRouter, HTTPException, Request
from .models import ChatRequest, ContextRequest

# FastAPI router for generate endpoints
generate_router = APIRouter()

@generate_router.post(
    "/chat-workflow",
    response_model=dict,
    summary="Process chat workflow with a given prompt"
)
async def chat_workflow(request: Request, payload: ChatRequest):
    """
    Takes a prompt and returns the response from the SageWorkflow agent.
    """
    try:
        # Access the workflow instance from app state
        workflow = request.app.state.workflow
        result_dict = await workflow.chat_with_agent_workflow(payload.prompt)
        # Check if there was an error during workflow execution
        if result_dict.get("error"): 
            raise HTTPException(status_code=500, detail=result_dict["response"])
        return result_dict # Return the dictionary containing response and ctx_id
    except HTTPException as http_exc:
        # Re-raise HTTPException to let FastAPI handle it
        raise http_exc
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@generate_router.get(
    "/get-contexts",
    response_model=dict,
    summary="Retrieve list of available contexts"
)
async def get_contexts(request: Request):
    """
    Returns the list of context identifiers available in the workflow.
    """
    try:
        contexts = request.app.state.workflow.ctx_index
        return {"contexts": contexts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@generate_router.post(
    "/reset-context",
    response_model=dict,
    summary="Reset the current context in the workflow"
)
async def reset_context(request: Request):
    """
    Resets the current conversation context in the SageWorkflow.
    """
    try:
        await request.app.state.workflow.reset_context()
        return {"message": "Context reset successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@generate_router.post(
    "/load-context",
    response_model=dict,
    summary="Load a specific context by ID"
)
async def load_context(request: Request, payload: ContextRequest):
    """
    Loads the conversation history for a given context ID.
    """
    try:
        chat_history = await request.app.state.workflow.load_context(payload.id)
        if chat_history is None:
            raise HTTPException(status_code=404, detail="Context not found")
        return {"chat_history": chat_history}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@generate_router.post(
    "/delete-context",
    response_model=dict,
    summary="Delete a context by ID"
)
async def delete_context(request: Request, payload: ContextRequest):
    """
    Deletes a stored context by its ID from the SageWorkflow.
    """
    try:
        request.app.state.workflow.delete_context(payload.id)
        return {"message": "Context deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))