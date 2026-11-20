*** Settings ***
Documentation    Run the VirtualBox ERP fixture and verify its three replay outcomes.
Library          Process

*** Variables ***
${VAMP_REPO}              %{VAMP_DEMO_REPO=}
${VM_UUID}                %{VAMP_DEMO_VM=}
${GUEST_USER}             %{VAMP_DEMO_GUEST_USER=}
${GUEST_PASSWORD_FILE}    %{VAMP_DEMO_GUEST_PASSWORD_FILE=}
${V1_DOWNLOAD}            %{VAMP_DEMO_V1_DOWNLOAD=}
${V2_DOWNLOAD}            %{VAMP_DEMO_V2_DOWNLOAD=}
${HOST_URL}               %{VAMP_DEMO_HOST_URL=http://127.0.0.1:18080}
${GUEST_URL}              %{VAMP_DEMO_GUEST_URL=http://10.0.2.2:18080}

*** Test Cases ***
ERP Replay Stops On Layout Change And Verified Downloads Match
    FOR    ${setting}    IN    ${VAMP_REPO}    ${VM_UUID}    ${GUEST_USER}
    ...    ${GUEST_PASSWORD_FILE}    ${V1_DOWNLOAD}    ${V2_DOWNLOAD}
        Should Not Be Empty    ${setting}    Configure the required VAMP_DEMO variables before running.
    END
    ${python}=    Evaluate    sys.executable    modules=sys
    ${result}=    Run Process    ${python}    ${CURDIR}${/}virtualbox_demo.py
    ...    --vamp-repo    ${VAMP_REPO}    --vm    ${VM_UUID}
    ...    --guest-user    ${GUEST_USER}    --guest-password-file    ${GUEST_PASSWORD_FILE}
    ...    --v1-download    ${V1_DOWNLOAD}    --v2-download    ${V2_DOWNLOAD}
    ...    --host-url    ${HOST_URL}    --guest-url    ${GUEST_URL}
    ...    cwd=${CURDIR}    timeout=4 minutes    on_timeout=terminate
    Should Be Equal As Integers    ${result.rc}    0    ${result.stderr}
    ${stages}=    Evaluate    json.loads('[' + ','.join($result.stdout.splitlines()) + ']')    modules=json
    Length Should Be    ${stages}    3
    Should Be Equal    ${stages}[0][stage]    v1_download_verified
    Should Be Equal    ${stages}[1][stage]    v1_replay_blocked_on_v2
    Should Be Equal As Integers    ${stages}[1][actions_completed]    0
    Should Be Equal    ${stages}[2][stage]    v2_download_verified
    Should Be Equal    ${stages}[0][sha256]    ${stages}[2][sha256]
