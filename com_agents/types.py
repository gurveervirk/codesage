from llama_index.core.bridge.pydantic import BaseModel, Field
from llama_index.core import Settings, PromptTemplate
from typing import List

class SubTask(BaseModel):
    """A single sub-task in a plan."""
    name: str = Field(..., description="Name of the subtask.")
    description: str = Field(..., description="Description of the subtask.")
    dependencies: List[str] = Field(
        ..., 
        description="List of subtask names that this subtask depends on."
    )

class Plan(BaseModel):
    """Plan represented as a sequence of subtasks."""

    sub_tasks: List[SubTask] = Field(..., description="List of subtasks in the plan.")

DEFAULT_INITIAL_PLAN_PROMPT = """
You are a planner for a code generation task. Given an overall task (a user's coding request) and a set of relevant root modules (representing a Python codebase), create a comprehensive, step-by-step plan to accomplish the task.

**Instructions:**

1.  **Sub-task Granularity:** Break down the task into manageable sub-tasks. Each sub-task should represent a clear and well-defined goal. While atomic tasks are often ideal, aim for a level of granularity that allows you to find the *best available* functionality in the existing codebase (represented by the root modules), even if it's not perfectly atomic. It must be reasonably low level so that it can be fulfilled by an available BEST HIGH LEVEL functionality in the tree.
2.  **Root Module Context:** Carefully consider the provided root modules. Use them to guide your plan and to identify potential functionalities.
3.  **Sub-task Structure:** Each sub-task should describe *what* needs to be done.
4.  **If a sub-task requires it, make sure the step consists of both:**
    * "First: Find a relevant entity/functionality (in the root modules)."
    * "Second: Generate code to utilize the entity to complete the task."
5.  **Root Module Assignment:** If a particular sub-task is best fulfilled by a specific root module, mention that module's name in the sub-task description (e.g., "Find a functionality in module 'module_name' that..."). If a sub task does not depend on a root module, do not mention it.
6.  **No Assumptions:** Do not assume the existence of any specific functions or libraries beyond what is described in the root modules.

Keep in mind not every task needs to be decomposed into multiple sub-tasks if it is simple enough. The plan should end with a sub-task that can achieve the overall task.

The overall goal is to generate Python code. The code will be constructed by finding existing methods/functions in a Neo4j knowledge graph, described through the following root modules (Name and Description):
{root_modules_str}
You do *not* need to interact with the graph. Your job is *only* to create the plan.

Do NOT mention any specific tools or libraries.

Overall Task: {task}

Be as detailed as possible in your sub-task descriptions. Focus on WHAT functionality is needed. Each sub-task input should be a clear and concise description.
"""

DEFAULT_PLAN_REFINE_PROMPT = """
You are a planner for a code generation task. You are given an overall task, a set of tools (for context), a list of completed sub-tasks (with their outputs), and a list of remaining sub-tasks. Your goal is to refine the plan, ensuring it will still lead to the successful completion of the overall task.

**Focus:**

*   **Atomicity:** Each sub-task should still represent a SINGLE, fundamental functionality, likely corresponding to a METHOD or FUNCTION in a Python codebase.
*   **Completeness:** Critically evaluate whether the completed sub-tasks, combined with the *original* remaining sub-tasks, will actually fulfill the overall task.
*   **Modification:**
    *   If the existing plan is sufficient, no modifications are necessary.
    *   If the existing plan is NOT sufficient, modify the REMAINING sub-tasks. You can:
        *   **Add NEW sub-tasks:** If necessary functionalities are missing.
        *   **Remove sub-tasks:** If they are redundant or no longer relevant.
        *   **Modify existing sub-tasks:** If their input or expected output needs adjustment.
        * Do NOT repeat tasks that are already completed.
* **Do NOT generate any code in any sub-task.** You are to only refine the plan and sub-tasks.

The code will be constructed by finding existing methods/functions in a Neo4j knowledge graph representing a Python codebase. You do *not* need to query the graph yourself.

The available tools (for context only) are:
{tools_str}

Completed Sub-Tasks + Outputs:
{completed_outputs}

Remaining Sub-Tasks:
{remaining_sub_tasks}

Overall Task: {task}

Be as detailed as possible in your sub-task descriptions. Focus on WHAT functionality is needed, not HOW it will be implemented.  Each sub-task input should be a clear, concise description of the desired functionality. Do not mention the available tools within the plan, it has been provided only for context.
"""

current_plan: Plan = None
async def plan(
    input: str,
    refine: bool = False,
    replan: bool = False,
):
    """
    Planning function based on input.

    Args:
        input: Input to plan on.
        refine: Whether to refine the current plan.
        replan: Whether to replan from scratch.

    Returns:
        Plan: Plan based on input.
    """

    global current_plan

    if replan:
        current_plan = None

    if current_plan is None:
        current_plan = Plan(
            sub_tasks=[
                SubTask(
                    name="subtask1",
                    description="Description of subtask1",
                    dependencies=[]
                ),
                SubTask(
                    name="subtask2",
                    description="Description of subtask2",
                    dependencies=["subtask1"]
                ),
                SubTask(
                    name="subtask3",
                    description="Description of subtask3",
                    dependencies=["subtask2"]
                )
            ]
        )

    return current_plan