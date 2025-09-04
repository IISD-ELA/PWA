#!/bin/bash
set -eo pipefail

LOCAL_PORT=3391
REMOTE_PORT=3389

JSON_PARAMS=$(aws --profile iisd --region ca-central-1 ssm get-parameters --names "/iisd-ela/config/ops/ops_instance_id" "/iisd-ela/config/windows/private_ip" --query 'Parameters[*].[Name,Value]' --output json)

WINDOWS_PRIVATE_IP=$(echo $JSON_PARAMS | jq -r ".[] | select(.[0] == \"/iisd-ela/config/windows/private_ip\") | .[1]")
OPS_INSTANCE_ID=$(echo $JSON_PARAMS | jq -r ".[] | select(.[0] == \"/iisd-ela/config/ops/ops_instance_id\") | .[1]")

aws --profile iisd --region ca-central-1 ssm start-session --target $OPS_INSTANCE_ID --document-name "AWS-StartPortForwardingSessionToRemoteHost" --parameters "portNumber=[$REMOTE_PORT],localPortNumber=[$LOCAL_PORT],host=[$WINDOWS_PRIVATE_IP]"
