***Settings***
Documentation  This is a sample resource file with 3 keywords.

***Keywords***
Log Message
    [Arguments]
    Log  ${message}

Calculate Sum
    [Arguments]  ${num1}  ${num2}
    ${sum} =  Evaluate  ${num1} + ${num2}
    [Return]  ${sum}

Verify Text Contains
    [Arguments]  ${text}  ${substring}
    Should Contain  ${text}  ${substring}