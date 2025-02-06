from llama_index.agent.lats import LATSAgentWorker
from llama_index.core.agent import (
    AgentChatResponse,
    ReActOutputParser,
    Task,
)
from typing import Any, Dict, List, Optional, Tuple, cast
from llama_index.core.utils import print_text
from llama_index.core.agent.react.types import (
    ActionReasoningStep,
    BaseReasoningStep,
    ObservationReasoningStep,
    ResponseReasoningStep,
)
from llama_index.agent.lats.types import Candidates
from llama_index.core.tools import ToolSelection, acall_tool_with_selection
from .types import COMEvaluation, COMSearchNode, DEFAULT_COM_CANDIDATE_EXPANSION_PROMPT, DEFAULT_COM_REFLECTION_PROMPT
import asyncio

class COMAgentWorker(LATSAgentWorker):
    """COM Agent Worker class."""

    def __init__(self, *args, reflection_prompt=None, candidate_expansion_prompt=None, **kwargs):
        self.candidate_expansion_prompt = candidate_expansion_prompt
        super().__init__(
            *args,
            reflection_prompt=reflection_prompt or DEFAULT_COM_REFLECTION_PROMPT,
            candidate_expansion_prompt=candidate_expansion_prompt or DEFAULT_COM_CANDIDATE_EXPANSION_PROMPT,
            **kwargs,
        )

    def _initialize_state(self, task: Task, **kwargs: Any) -> Dict[str, Any]:
        """Initialize state."""
        # initialize root node
        root_node = COMSearchNode(
            current_reasoning=[ObservationReasoningStep(observation=task.input)],
            evaluation=COMEvaluation(score=1),  # evaluation for root node is blank
        )
        return {"count": 0, "solution_queue": [], "root_node": root_node}

    async def _arun_candidate(
        self,
        node: COMSearchNode,
        task: Task,
    ) -> List[BaseReasoningStep]:
        """Generate candidate for a given node.

        Generically we sample the action space to generate new candidate nodes.

        Practically since we're using a ReAct powered agent, this means
        using generating a ReAct trajectory, running a tool.

        """
        output_parser = ReActOutputParser()
        # format react prompt
        formatted_prompt = self.chat_formatter.format(
            self.tools,
            chat_history=task.memory.get(),
            current_reasoning=node.current_reasoning,
        )
        # run LLM
        response = await self.llm.achat(formatted_prompt)
        # parse output into reasoning step

        try:
            reasoning_step = output_parser.parse(response.message.content)
        except ValueError as e:
            reasoning_step = ResponseReasoningStep(
                thought=response.message.content,
                response=f"Encountered an error parsing: {e!s}",
            )
        # get response or run tool
        if reasoning_step.is_done:
            reasoning_step = cast(ResponseReasoningStep, reasoning_step)
            current_reasoning = [reasoning_step]
        else:
            reasoning_step = cast(ActionReasoningStep, reasoning_step)
            tool_selection = ToolSelection(
                tool_id=reasoning_step.action,
                tool_name=reasoning_step.action,
                tool_kwargs=reasoning_step.action_input,
            )
            try:
                tool_output = await acall_tool_with_selection(
                    tool_selection, self.tools, verbose=self.verbose
                )
            except Exception as e:
                tool_output = f"Encountered error: {e!s}"
            observation_step = ObservationReasoningStep(observation=str(tool_output))
            current_reasoning = [reasoning_step, observation_step]

        return current_reasoning
    
    async def _get_next_candidates(
        self,
        cur_node: COMSearchNode,
        input: str,
    ) -> List[str]:
        """Get next candidates."""
        # get candidates
        history_str = "\n".join([s.get_content() for s in cur_node.current_reasoning])

        candidates = await self.llm.astructured_predict(
            Candidates,
            prompt=self.candidate_expansion_prompt,
            query=input,
            conversation_history=history_str,
            num_candidates=self.num_expansions,
        )
        candidate_strs = candidates.candidates[: self.num_expansions]
        if self.verbose:
            print_text(f"> Got candidates: {candidate_strs}\n", color="yellow")

        return candidate_strs

    def _initialize_state(self, task: Task, **kwargs: Any) -> Dict[str, Any]:
        """Initialize state."""
        # initialize root node
        root_node = COMSearchNode(
            current_reasoning=[ObservationReasoningStep(observation=task.input)],
            evaluation=COMEvaluation(score=1),  # evaluation for root node is blank
        )
        return {"count": 0, "solution_queue": [], "root_node": root_node}

    async def _aevaluate(
        self,
        cur_node: COMSearchNode,
        current_reasoning: List[BaseReasoningStep],
        input: str,
    ) -> float:
        """Evaluate."""
        all_reasoning = cur_node.current_reasoning + current_reasoning
        history_str = "\n".join([s.get_content() for s in all_reasoning])
        evaluation = await self.llm.astructured_predict(
            COMEvaluation,
            prompt=self.reflection_prompt,
            query=input,
            conversation_history=history_str,
        )
        if self.verbose:
            print_text(
                f"> Evaluation for input {input}\n: {evaluation}\n\n", color="pink"
            )

        return evaluation
    
    def _update_state(
        self,
        node: COMSearchNode,
        current_reasoning: List[BaseReasoningStep],
        evaluation: COMEvaluation,
    ) -> COMSearchNode:
        """Update state."""
        # create child node
        new_node = COMSearchNode(
            current_reasoning=node.current_reasoning + current_reasoning,
            parent=node,
            children=[],
            evaluation=evaluation,
        )
        node.children.append(new_node)

        # backpropagate the reward
        new_node.backpropagate(evaluation.score)

        return new_node

    async def _arun_step(
        self, state: Dict[str, Any], task: Task, input: Optional[str] = None
    ) -> Tuple[AgentChatResponse, bool]:
        """Run step.

        Returns:
            Tuple of (agent_response, is_done)

        """
        root_node = state["root_node"]
        cur_node = root_node.get_best_leaf()
        if self.verbose:
            print_text(
                f"> Selecting node to expand: {cur_node.answer}\n", color="green"
            )

        # expand the given node, generate n candidate nodes
        new_candidates = await self._get_next_candidates(
            cur_node,
            task.input,
        )

        new_nodes = []
        for candidate in new_candidates:
            new_nodes.append(
                self._update_state(
                    cur_node,
                    [ObservationReasoningStep(observation=candidate)],
                    COMEvaluation(score=1),  # evaluation for candidate node is blank
                )
            )

        # expand the given node, generate n candidates
        # for each candidate, run tool, get response

        solution_queue: List[COMSearchNode] = state["solution_queue"]

        # first, generate the candidates
        candidate_jobs = [
            self._arun_candidate(new_node, task) for new_node in new_nodes
        ]
        all_new_reasoning_steps = await asyncio.gather(*candidate_jobs)
        if self.verbose:
            for new_reasoning_steps in all_new_reasoning_steps:
                out_txt = "\n".join([s.get_content() for s in new_reasoning_steps])
                print_text(f"> Generated new reasoning step: {out_txt}\n", color="blue")
        # then, evaluate the candidates
        eval_jobs = [
            self._aevaluate(new_node, new_reasoning_steps, task.input)
            for new_node, new_reasoning_steps in zip(new_nodes, all_new_reasoning_steps)
        ]
        evaluations = await asyncio.gather(*eval_jobs)
        # then, update the state
        for new_reasoning_steps, cur_new_node, evaluation in zip(
            all_new_reasoning_steps, new_nodes, evaluations
        ):
            new_node = self._update_state(cur_new_node, new_reasoning_steps, evaluation)
            if new_node.is_done:
                if self.verbose:
                    print_text(
                        f"> Found solution node: {new_node.answer}\n", color="cyan"
                    )
                solution_queue.append(new_node)

        # check if done
        state["count"] += 1
        if self.max_rollouts == -1 and solution_queue:
            is_done = True
        elif self.max_rollouts > 0 and state["count"] >= self.max_rollouts:
            is_done = True
        else:
            is_done = False

        # determine response
        if solution_queue:
            best_solution_node = max(solution_queue, key=lambda x: x.score)
            response = best_solution_node.evaluation.entity_name
        else:
            response = "I am still thinking."

        if self.verbose:
            print_text(f"> Got final response: {response!s}\n", color="green")

        # return response
        return AgentChatResponse(response=str(response)), is_done