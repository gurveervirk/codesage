"""
Tests for the MainWkflw workflow.
"""
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call
import json

from llama_index.core.workflow import StartEvent, Context, StopEvent
from llama_index.core.llms import ChatMessage, CompletionResponse
from llama_index.core.memory import Memory

# Adjust the import path based on your project structure
from backend.lib_sage.sage_workflow.wkflw import MainWkflw
from backend.lib_sage.sage_workflow.events import (
    OrchestrationEvent,
    RootModuleSearchEvent,
    CodeEntitySearchEvent,
    CodeGenerationEvent,
    EntitiesEvent
)
from backend.utils.models import (
    Plan,
    OrchestrationResult,
    RootModuleSearchResult,
    CodeEntitySearchResult
)


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mocks all external dependencies for the workflow."""
    with patch('backend.code_sage.sage_workflow.wkflw.GoogleGenAI') as mock_google_genai, \
         patch('backend.code_sage.sage_workflow.wkflw.HuggingFaceEmbedding'), \
         patch('backend.code_sage.sage_workflow.wkflw.COMStore') as mock_com_store, \
         patch('backend.code_sage.sage_workflow.wkflw.config') as mock_config, \
         patch('backend.code_sage.sage_workflow.wkflw.FunctionAgent') as mock_function_agent:
        
        mock_config.GOOGLE_GENAI_API_KEY = "test_key"
        mock_config.NEO4J_URI = "bolt://localhost:7687"
        mock_config.NEO4J_USER = "neo4j"
        mock_config.NEO4J_PASSWORD = "password"

        mock_llm_instance = MagicMock()
        mock_llm_instance.as_structured_llm.return_value = AsyncMock()
        mock_llm_instance.structured_predict_without_function_calling = AsyncMock(return_value="structured_output")
        mock_google_genai.return_value = mock_llm_instance
        
        mock_function_agent.return_value = MagicMock()

        yield {
            "GoogleGenAI": mock_google_genai,
            "COMStore": mock_com_store,
            "config": mock_config,
            "FunctionAgent": mock_function_agent
        }

@pytest_asyncio.fixture
async def workflow(mock_dependencies):
    """Provides a MainWkflw instance with mocked dependencies."""
    wf = MainWkflw()
    # Mock structured LLMs and agents created in __init__
    wf.planner = AsyncMock()
    wf.orchestrator = AsyncMock()
    wf.code_generator = AsyncMock()
    wf.root_module_searcher = MagicMock()
    wf.code_entity_searcher = MagicMock()
    wf.code_gen_orchestrator = MagicMock()
    wf.com_store = mock_dependencies["COMStore"]()
    return wf

@pytest.fixture
def mock_context():
    """Provides a mock workflow context."""
    ctx = MagicMock(spec=Context)
    # Simulate a state dictionary that persists across calls
    state_dict = {}
    async def get_state(key, default=None):
        return state_dict.get(key, default)
    
    async def set_state(key, value):
        state_dict[key] = value

    ctx.get = get_state
    ctx.set = set_state
    ctx.send_event = MagicMock()
    # Initialize with an empty state
    state_dict["state"] = {}
    return ctx

def test_mainwkflw_init(mock_dependencies):
    """Tests the initialization of MainWkflw."""
    with patch.object(MainWkflw, '_init_tools') as mock_init_tools, \
         patch.object(MainWkflw, '_init_agents') as mock_init_agents, \
         patch.object(MainWkflw, '_init_sllms') as mock_init_sllms:
        
        wf = MainWkflw()
        
        mock_dependencies["COMStore"].assert_called_once()
        mock_init_tools.assert_called_once()
        mock_init_agents.assert_called_once()
        mock_init_sllms.assert_called_once()
        assert wf.retries == 5

@pytest.mark.asyncio
async def test_retrieve_relevant_root_modules(workflow, mock_context):
    """Tests retrieval of relevant root modules."""
    mock_results = {"raw": ["raw_data"], "formatted_results": "formatted_data"}
    workflow.com_store.retrieve_relevant_root_modules.return_value = mock_results
    
    result = await workflow.retrieve_relevant_root_modules(mock_context, "test query", 5)
    
    workflow.com_store.retrieve_relevant_root_modules.assert_called_once_with(query="test query", top_k=5)
    mock_context.send_event.assert_called_once_with(EntitiesEvent(entities=["raw_data"]))
    assert result == "formatted_data"

@pytest.mark.asyncio
async def test_get_info_for_entities(workflow, mock_context):
    """Tests getting information for entities, handling found and not found cases."""
    # Case 1: All entities found
    workflow.com_store.get_info_for_entities.return_value = {"raw": [{"name": "entity1"}], "formatted_results": "formatted_info"}
    
    result = await workflow.get_info_for_entities(mock_context, ["entity1"])
    
    workflow.com_store.get_info_for_entities.assert_called_with(["entity1"])
    mock_context.send_event.assert_called_with(EntitiesEvent(entities=[{"name": "entity1"}]))
    assert result["results"] == [{"name": "entity1"}]
    assert result["not_found_entities"] == {}

    # Reset mocks for Case 2
    mock_context.send_event.reset_mock()
    workflow.com_store.get_info_for_entities.reset_mock()
    workflow.com_store.get_full_path_names = MagicMock(return_value={"entity2": "path/to/entity2"})

    # Case 2: Some entities not found
    workflow.com_store.get_info_for_entities.return_value = {"raw": [None], "formatted_results": ""}
    
    result = await workflow.get_info_for_entities(mock_context, ["entity2"])
    
    workflow.com_store.get_info_for_entities.assert_called_with(["entity2"])
    mock_context.send_event.assert_called_with(EntitiesEvent(entities=[]))
    workflow.com_store.get_full_path_names.assert_called_with(["entity2"])
    assert result["results"] == []
    assert result["not_found_entities"] == {"entity2": "path/to/entity2"}

@pytest.mark.asyncio
async def test_plan_step(workflow, mock_context):
    """Tests the plan step of the workflow."""
    start_event = StartEvent(input="test prompt")
    mock_plan = Plan(objective="test objective", requirements=["req1"])
    mock_completion_response = MagicMock(spec=CompletionResponse, raw=mock_plan)
    workflow.planner.acomplete.return_value = mock_completion_response
    
    result = await workflow.plan(mock_context, start_event)
    
    workflow.planner.acomplete.assert_awaited_once()
    assert (await mock_context.get("state"))["plan"]["objective"] == "test objective"
    assert isinstance(result, OrchestrationEvent)

@pytest.mark.asyncio
async def test_orchestrate_step(workflow, mock_context):
    """Tests the orchestrate step of the workflow."""
    state = await mock_context.get("state")
    state["plan"] = {"objective": "test", "requirements": ["req1"]}
    await mock_context.set("state", state)
    
    orchestration_event = OrchestrationEvent()
    
    mock_orchestration_result = OrchestrationResult(
        analysis="test analysis", action="RootModuleSearchEvent", prompt="search prompt"
    )
    mock_chat_response = MagicMock(message=ChatMessage(content=mock_orchestration_result.model_dump_json()))
    workflow.orchestrator.achat.return_value = mock_chat_response
    
    result = await workflow.orchestrate(mock_context, orchestration_event)
    
    workflow.orchestrator.achat.assert_awaited_once()
    assert isinstance(result, RootModuleSearchEvent)
    assert result.prompt == "search prompt"

@pytest.mark.asyncio
async def test_root_module_search_step(workflow, mock_context):
    """Tests the root module search step."""
    rms_event = RootModuleSearchEvent(prompt="find root modules")
    
    workflow.run_handler = AsyncMock(return_value="some response")
    mock_search_result = RootModuleSearchResult(end=True, relevant_root_modules=["module1"])
    workflow.convert_to_structured_output = AsyncMock(return_value=mock_search_result)
    
    result = await workflow.root_module_search(mock_context, rms_event)
    
    workflow.root_module_searcher.run.assert_called_once()
    assert isinstance(result, OrchestrationEvent)
    assert result.result_keys["Most Relevant Root Modules in order of relevance"] == ["module1"]

@pytest.mark.asyncio
async def test_code_entity_search_step(workflow, mock_context):
    """Tests the code entity search step."""
    ces_event = CodeEntitySearchEvent(prompt="find entities", root_module="module1")
    
    response_json = json.dumps({
        "end": True, 
        "most_relevant_code_entity": "entity1", 
        "runner_up_code_entities": ["entity2"]
    })
    workflow.run_handler = AsyncMock(return_value=response_json)
    
    result = await workflow.code_entity_search(mock_context, ces_event)
    
    workflow.code_entity_searcher.run.assert_called_once()
    assert isinstance(result, OrchestrationEvent)
    assert result.result_keys["Most Relevant Code Entity"] == "entity1"

@pytest.mark.asyncio
async def test_code_generation_step_entities_not_found(workflow, mock_context):
    """Tests code generation when some entities are not found."""
    cg_event = CodeGenerationEvent(prompt="gen code", relevant_code_entities=["entity1", "entity2"])
    
    async def mock_get_info(*args, **kwargs):
        return {
            "results": [{"name": "entity1_info"}],
            "not_found_entities": {"entity2": "path/to/entity2"}
        }

    workflow.get_info_for_entities = AsyncMock(side_effect=mock_get_info)
    
    result = await workflow.code_generation(mock_context, cg_event)
    
    workflow.get_info_for_entities.assert_awaited_once_with(mock_context, ["entity1", "entity2"])
    assert isinstance(result, OrchestrationEvent)
    assert "Entities not found" in result.result_keys["Entities not found, please check and return correct full path names for the following"]

@pytest.mark.asyncio
async def test_code_generation_step_no_entities_provided(workflow, mock_context):
    """Tests code generation with no entities provided, expecting a ValueError."""
    cg_event = CodeGenerationEvent(prompt="gen code", relevant_code_entities=[])
    
    with pytest.raises(ValueError, match="No relevant code entities provided for code generation."):
        await workflow.code_generation(mock_context, cg_event)

def test_create_structured_llm(workflow):
    """Tests the creation of structured LLMs."""
    class MockOutput: pass

    with patch('backend.code_sage.sage_workflow.wkflw.DEFAULT_LLM') as mock_default, \
         patch('backend.code_sage.sage_workflow.wkflw.LITE_LLM') as mock_lite, \
         patch('backend.code_sage.sage_workflow.wkflw.ADVANCED_LLM') as mock_advanced:
        
        workflow.create_structured_llm("default", MockOutput)
        mock_default.as_structured_llm.assert_called_once_with(output_cls=MockOutput)

        workflow.create_structured_llm("lite", MockOutput)
        mock_lite.as_structured_llm.assert_called_once_with(output_cls=MockOutput)

        workflow.create_structured_llm("advanced", MockOutput)
        mock_advanced.as_structured_llm.assert_called_once_with(output_cls=MockOutput)

        with pytest.raises(ValueError, match="Unknown model type: unknown"):
            workflow.create_structured_llm("unknown", MockOutput)

@pytest.mark.asyncio
async def test_convert_to_structured_output(workflow):
    """Tests the conversion of a string response to a structured output."""
    class MockOutput: pass

    with patch('backend.code_sage.sage_workflow.wkflw.LITE_LLM') as mock_lite_llm:
        mock_lite_llm.structured_predict_without_function_calling = AsyncMock(return_value="structured_output")
        
        result = await workflow.convert_to_structured_output("some response", MockOutput, model_type="lite")
        
        mock_lite_llm.structured_predict_without_function_calling.assert_awaited_once()
        assert result == "structured_output"
