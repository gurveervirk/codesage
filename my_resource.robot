*** Keywords ***
My First Keyword
    Log    This is the first keyword

Another Keyword With Args
    [Arguments]    ${arg1}    ${arg2}
    Log    Args: ${arg1}, ${arg2}

Keyword Without Steps
    [Documentation]    This keyword has no steps.