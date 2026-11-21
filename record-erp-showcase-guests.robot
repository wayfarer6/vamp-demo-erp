*** Settings ***
Documentation    Capture the two ERP guest screens during the guided showcase.
Library          Process
Library          OperatingSystem
Library          Collections

*** Variables ***
${SECONDS}    480
${FPS}        4
${TRANSCRIPT}    ${EMPTY}
${REPAIR_TRANSCRIPT}    ${EMPTY}
${STOP_FILE}     ${EMPTY}

*** Test Cases ***
Capture The Target And Isolated ERP Guests
    ${python}=    Evaluate    sys.executable    modules=sys
    ${args}=    Create List    ${CURDIR}${/}record-erp-showcase-guests.py
    ...    ${TARGET_VM}    ${SCRATCH_VM}    ${VIDEO}    --seconds    ${SECONDS}
    ...    --fps    ${FPS}    --language    ${LANGUAGE}
    IF    $TRANSCRIPT
        Append To List    ${args}    --transcript    ${TRANSCRIPT}
    END
    IF    $REPAIR_TRANSCRIPT
        Append To List    ${args}    --transcript    ${REPAIR_TRANSCRIPT}
    END
    IF    $STOP_FILE
        Append To List    ${args}    --stop-file    ${STOP_FILE}
    END
    ${result}=    Run Process    ${python}    @{args}
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}${\n}${result.stderr}
    File Should Exist    ${VIDEO}
    Log    ${result.stdout}
