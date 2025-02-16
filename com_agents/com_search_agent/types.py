#@title Create necessary types

from llama_index.core import PromptTemplate
from llama_index.core.bridge.pydantic import Field, BaseModel
from llama_index.core.agent.react.types import (
    BaseReasoningStep,
    ResponseReasoningStep,
)
from typing import List, Optional
import math

DEFAULT_COM_REFLECTION_PROMPT_STR = """
Given a query and the current state of graph traversal, evaluate the progress in finding a relevant **METHOD or FUNCTION** within the Python code graph. The primary objective is to find and return the **NAME** of the **METHOD or FUNCTION** that best satisfies the query, not to generate any code.

Consider the following:

- **Correctness**: Are we exploring entities (ROOT_MODULE, MODULE, CLASS, METHOD, FUNCTION) that are potentially relevant to the query, given the graph structure and relationships (ROOT_MODULE-HAS_SUBMODULE->MODULE, MODULE-HAS_SUBMODULE->MODULE, MODULE-HAS_CLASS->CLASS, CLASS-HAS_CLASS->CLASS, CLASS-HAS_METHOD->METHOD, MODULE-HAS_FUNCTION->FUNCTION)?
- **Efficiency**: Are we prioritizing the exploration of entities that have a higher cosine similarity score, indicating a stronger semantic match to the query?
- **Completeness**: Have we found a potential solution (a METHOD or FUNCTION node)? If so, how well does its description match the query based on its cosine similarity score?

Based on your assessment, provide an INTEGER score between 1 and 10, where:
- 10 indicates an almost perfect match: a relevant **METHOD or FUNCTION** has been found, its description strongly aligns with the query, and it has a high cosine similarity score.
- 1 indicates a complete mismatch or a dead end: the current path is unlikely to lead to a relevant **METHOD or FUNCTION**.

Set `is_done` to True **only** when you find a **METHOD or FUNCTION** that satisfies the query. **Do not stop exploring if you find other types of entities.**

Your task is to find and return the **NAME** of the **METHOD or FUNCTION** only. Do not generate any code or explanations.

Query: {query}
Conversation History:
{conversation_history}
"""

DEFAULT_COM_CANDIDATE_EXPANSION_PROMPT_STR = """
Given the current node in the graph and the query, suggest the next steps for traversing the Python code graph to find a relevant **METHOD or FUNCTION**. The primary objective is to find and return the **NAME** of the **METHOD or FUNCTION** that best satisfies the query, not to generate any code.

Consider the following:

- **Node Type and Available Relationships**:
    - If the current node is a METHOD or FUNCTION, suggest evaluating its description against the query to determine if it's a suitable match. **If it's a match, your task is complete. Return the METHOD or FUNCTION's name immediately.**
    - If the current node is a ROOT_MODULE, MODULE, or CLASS, use the `retrieve_relevant_children_in_subtree` tool to find the most relevant immediate children based on cosine similarity to the query. Prioritize exploring children with higher similarity scores.
- **Root Module Exploration**: If the current exploration path seems unpromising, consider using the `retrieve_relevant_root_modules` tool to identify and explore alternative root modules that might contain a relevant METHOD or FUNCTION.
- **Query Relevance**: Prioritize actions that are more likely to lead to a METHOD or FUNCTION closely related to the query.

Suggest **up to {num_candidates}** of the following actions, ensuring that the suggested actions are **distinct and not extremely similar** to each other. It's acceptable to suggest **fewer** actions if there are not enough distinct and relevant options:

- "Evaluate the current node" (if it's a METHOD or FUNCTION).
- "Explore the most relevant children of the current node using `retrieve_relevant_children_in_subtree`".

When using the `retrieve_relevant_children_in_subtree` action, make sure your query is descriptive and not just a couple of words.

Remember, your goal is to efficiently find and return the **NAME** of a **METHOD or FUNCTION** whose description closely matches the query. **Stop immediately once a suitable METHOD or FUNCTION is found and return its NAME.**
Provide your suggested next actions **concisely, focusing on the actions themselves**.

Query: {query}
Conversation History:
{conversation_history}
"""

DEFAULT_COM_REFLECTION_PROMPT = PromptTemplate(DEFAULT_COM_REFLECTION_PROMPT_STR)
DEFAULT_COM_CANDIDATE_EXPANSION_PROMPT = PromptTemplate(DEFAULT_COM_CANDIDATE_EXPANSION_PROMPT_STR)

class COMEvaluation(BaseModel):
    """Evaluation of a given node."""

    score: int = Field(
        description="Score of the reflection indicating **correctness**. Integer from 1-10",
        le=10,
        ge=0,
    )
    is_done: bool = Field(
        False, description="Whether the answer is found yet (**completeness**)."
    )
    reasoning: str = Field(
        default="", description="Reasoning and justification for the evaluation."
    )
    entity_name: str = Field(
        default="", description="Name of the entity IF the answer is found."
    )

class COMSearchNode(BaseModel):
    """Search node.

    Named differently from `Node` which is a core module in LlamaIndex.

    """

    current_reasoning: List[BaseReasoningStep] = Field(
        ..., description="Current reasoning."
    )
    parent: Optional["COMSearchNode"] = Field(default=None, description="Parent node.")
    children: List["COMSearchNode"] = Field(
        default_factory=list, description="Children nodes."
    )
    evaluation: COMEvaluation = Field(..., description="Evaluation of the node.")
    visits: int = Field(default=0, description="Number of visits to the node.")

    @property
    def answer(self) -> Optional[str]:
        """Answer."""
        if not self.current_reasoning:
            return None

        if isinstance(self.current_reasoning[-1], ResponseReasoningStep):
            return self.current_reasoning[-1].response
        else:
            return self.current_reasoning[-1].get_content()

    @property
    def is_done(self) -> bool:
        """Is the node done."""
        return self.evaluation.is_done

    @property
    def score(self) -> float:
        """Score of the node."""
        return self.evaluation.score

    @property
    def upper_confidence_bound(self) -> float:
        """Upper confidence bound."""
        return self.score + 1.0 * math.sqrt(math.log(self.parent.visits) / self.visits)

    def backpropagate(self, reward: float) -> None:
        """Backpropagate the reward."""
        cur_node = self
        while cur_node is not None:
            cur_node.visits += 1
            cur_node.evaluation.score = (
                reward + (cur_node.visits - 1) * cur_node.score
            ) / cur_node.visits
            cur_node = cur_node.parent

    def get_best_leaf(self) -> "COMSearchNode":
        """Get best leaf node.

        Get best leaf node across any children nodes.

        """
        # only get children that aren't done yet
        free_children = [c for c in self.children if not c.is_done]
        if not free_children:
            return self

        best_child = max(free_children, key=lambda x: x.upper_confidence_bound)
        return best_child.get_best_leaf()