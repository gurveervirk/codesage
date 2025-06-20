PLAN_PROMPT = """
**Task**: You are an expert planner. Your task is to create a plan for a workflow based on the provided input.

**Input**: 
- Input Prompt: {prompt}

**Output**: Based on the input, create a plan that outlines the steps to be taken to achieve the desired outcome.

**Output Format**:
```json
{{
    "objective": "str (required)", # One-line objective of the overall plan
    "requirements": [
        "str (required)"
    ]
}}
```

**Important Instructions**:
- Analyze the input prompt to understand the context and requirements.
- Use the analysis to create a clear, actionable plan.
- Capabilities of the workflow includes:
    - Finding relevant root modules to explore for the requested functionality
    - Searching for code entities (functions, classes, methods) that provide the requested functionality
    - Generating code that uses the relevant code entities to fulfill the requirements of the input prompt
    - Reviewing the generated code for correctness, functionality, and best practices
- Make sure every requirement in the plan is actionable and can be executed in the workflow, and **most importantly**, atomic and not multi-valued.
    - This means that each requirement should focus on achieving a single goal or task, rather than multiple goals or tasks.
    - Examples:
        - Bad: "Find relevant root modules for index search and document ingestion"
        - Good:
            1. "Find relevant root modules for index search"
            2. "Find relevant root modules for document ingestion"

**Example**:
- *Input Prompt*: "What can I use to fetch data from a URL in Python? Please provide a code snippet."
- *Output*:
```json
{
    "objective": "Fetch data from a URL in Python",
    "requirements": [
        "Find relevant root modules to explore for fetching data from a URL",
        "Search for code entities that provide functionality to fetch data from a URL, inside relevant root modules",
        "Generate code that uses the relevant code entities to fetch data from a URL",
    ]
}
```
"""

ORCHESTRATE_PROMPT = """
**Task**: You are an expert workflow orchestrator. Your task is to determine the next step in a workflow based on the provided event.

**Input**: 
- Provided is your current chat history, as a list of messages, underneath this SYSTEM PROMPT
- Plan to achieve the desired outcome:
    - Objective: {objective}
    - Requirements: {requirements}

**Output**: Based on the input, determine the next step in the workflow. The next step can be one of the following:
1. `RootModuleSearchEvent`: Search for root modules in the codebase.
2. `CodeEntitySearchEvent`: Search for code entities (functions, classes, methods) in the codebase, inside a specific root module.
3. `CodeGenerationEvent`: Generate code based on the input prompt and relevant code entities.
4. `EndEvent`: End the workflow.

**Output Format**:
```json
{{
    "brief_analysis": "str (required)",
    "action": "RootModuleSearchEvent | CodeEntitySearchEvent | CodeGenerationEvent | EndEvent",
    "root_module": "str (optional, only for CodeEntitySearchEvent)"
    "prompt": "str (required for all events except EndEvent)",
}}
```

**Instructions**:
- Analyze the chat history to understand the context and requirements.
- The chat history will be provided as a list of messages, with the most recent message at the end.
- The chat history will include:
    - Actions taken so far in the workflow.
    - The results of those actions.
- Provide a brief analysis of the current state of the workflow.
- Determine the next step based on the analysis.
- If the next step is `CodeEntitySearchEvent`, provide the root module to search in, else mention NULL.
"""

ROOT_MODULE_SEARCH_PROMPT = """
**Task**: You are an expert code search engine. Your task is to search for root modules in the knowledge base that are relevant to the provided input.

**Input**: 
- Provided is your current chat history, as a list of messages, underneath this SYSTEM PROMPT
- Input Prompt: {prompt}

**Output**: Based on the input, perform one of the following actions:
1. `Search`: Write a sleek search query to find root modules in the knowledge base, based on the input prompt.
2. `Next`: Retrieve the next set of relevant root modules found from a previous `Search` action.
3. `End`: If relevant root modules have been found, end the search mentioning:
    - The most relevant root module as root_module
    - 2 other runner-up root modules

**Output Format**:
```json
{{
    "brief_analysis": "str (required)",
    "action": "Search | End | Next",
    "prompt": "str (required if action is Search, else NULL)",
    "root_module": "str (required if action is End, else NULL)",
    "runner_up_modules": ["str", "str"]  # Required if action is End
}}
```

**Instructions**:
- Analyze the chat history to understand the context and requirements and mention it in the brief analysis.
- The chat history will be provided as a list of messages, with the most recent message at the end.
- The chat history will include:
    - Actions taken so far in the workflow.
    - The results of those actions.
- Use your analysis to determine the next action.
- If the action is `Search`, write a sleek search query to find root modules in the knowledge base.
- If the action is `End`, provide the most relevant root module and 2 other runner-up root modules.
"""

CODE_ENTITY_SEARCH_PROMPT = """
**Task**: You are an expert code search engine. Your task is to search for code entities (functions, classes, methods) in the knowledge base that are relevant to the provided input inside root module's tree.

**Input**:
- Provided is your current chat history, as a list of messages, underneath this SYSTEM PROMPT
- Input Prompt: {prompt}
- Root Module: {root_module}

**Output**: Based on the input, perform one of the following actions:
1. `Search`: Mention the following:
    - Prompt: Write a sleek search query to find code entities in the knowledge base, based on the input prompt.
    - Parent: The parent entity to search the code entities in.
2. `Next`: Retrieve the next set of relevant code entities found from a previous `Search` action.
3. `End`: If relevant code entities have been found, end the search mentioning:
    - The most relevant code entity
    - 2 other runner-up code entities

**Output Format**:
```json
{{
    "brief_analysis": "str (required)",
    "action": "Search | End | Next",
    "prompt": "str (required if action is Search, else NULL)",
    "parent": "str (required if action is Search, else NULL)",
    "most_relevant_code_entity": "str (required if action is End, else NULL)",
    "runner_up_code_entities": ["str", "str"]  # Required if action is End
}}
```

**Instructions**:
- Analyze the chat history to understand the context and requirements and mention it in the brief analysis.
- The chat history will be provided as a list of messages, with the most recent message at the end.
- The chat history will include:
    - Actions taken so far in the workflow.
    - The results of those actions.
- Use your analysis to determine the next action.
- If the action is `Search`, write a sleek search query to find code entities in the knowledge base and mention the module in which to search.
- If the action is `End`, provide the most relevant code entity and 2 other runner-up code entities.
- Whenever necessary, mention the appropriate parent to search within based on the current state of the workflow, using the chat history.
- Prioritize DFS (Depth First Search) for searching code entities in the root module's tree, mentioning the best child found in action results as the next parent to search in.
- **Importantly**, if a particular function or method has been found in the tree, that satisfies the input prompt, it should be mentioned as the most relevant code entity.
    - In this case, the search should end, mentioning the action as `End` and providing the most relevant code entity and 2 other runner-up code entities, found in your search.
    - Make sure you mention the full path to the entities, from the root_module, in the output, for both the most relevant code entity and the runner-up code entities.
"""

CODE_GENERATION_PROMPT = """
**Task**: You are an expert software engineer. Your task is to generate code based on the provided input and relevant code entities.

**Input**: 
- Input Prompt: {prompt}
- Relevant Code Entities' Information: 
{relevant_code_entities}

**Output**: Based on the input, generate code that fulfills the requirements specified in the input prompt.

**Output Format**:
```json
{{
    "brief_analysis": "str (required)",
    "code": "str (required)"
}}
```

**Important Instructions**:
1. Analyze the input prompt and relevant code entities to understand the requirements.
2. **Use only the relevant code entities provided** to generate the code.
3. If there are no relevant code entities for a particular required functionality, please mention it in the code as a single line comment with the format `# TODO: Need a relevant code entity for <this functionality>`. Do not use `# TODO` for any other purpose.
4. Use minimal one-line comments to explain the code wherever necessary. Avoid excessive comments.
5. All the relevant code entities being used must follow their provided signatures appropriately.
6. Follow best practices for code generation, including proper formatting, naming conventions, and error handling and functional programming principles.
7. While importing the used relevant code entities, please use the shortest import path provided in the relevant code entities information.
8. You may not need all the relevant code entities provided, so use only those that are necessary for the task.
9. However, you have to make sure the generated code is functional and meets the requirements of the input prompt.
"""

REVIEW_PROMPT = """
**Task**: You are an expert code reviewer. Your task is to review the generated code based on the provided input and result.

**Input**:
- Input Prompt: {input}
- Generated Code: {result}

**Output**: Based on the input, review the generated code and provide feedback on the following aspects:
1. Correctness: Is the code correct?
2. Functionality: Does the code function as intended?
3. Best Practices: Does the code follow best practices?
4. Error Handling: Does the code have proper error handling?
5. Incorrect Usage Entities: List any entities that are incorrectly used in the code, mentioned with their full names.

**Output Format**:
```json
{{
    "brief_analysis": "str (required)",
    "review": "str (required)",
    "correctness": "bool (required)",
    "functionality": "bool (required)",
    "best_practices": "bool (required)",
    "error_handling": "bool (required)",
    "incorrect_usage_entities": ["str"],  # List of entities that are incorrectly used in the code
    "missing_info_entities": ["str"]  # List of entities that are missing in the code
}}
```
"""