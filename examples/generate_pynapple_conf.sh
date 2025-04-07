#!/bin/bash
CONFIG_FILE="$(dirname "$0")/pynapple.astrolabe.conf"

# Function to retrieve the latest pod by name
get_pod() {
    local name=$1
    kubectl get pods --sort-by=.metadata.creationTimestamp | grep "$name" | tail -n 1 | awk '{print $1}'
}

# Retrieve the latest pods for pynapple1 and pynapple2
PY1_POD=$(get_pod pynapple1)
PY2_POD=$(get_pod pynapple2)

# Function to retrieve the public IP of the latest EC2 instance by name
get_instance() {
    local name=$1
    aws ec2 describe-instances \
        --filters "Name=instance-state-name,Values=pending,running" \
        --query 'Reservations[*].Instances[*].[LaunchTime, Tags[?Key==`Name`].Value | [0], PublicIpAddress]' \
        --output text | grep "$name" | sort -rk1 | head -n 1 | awk '{print $3}'
}

# Retrieve the latest instances for pynapple1 and pynapple2
PY1_INST=$(get_instance pynapple1)
PY2_INST=$(get_instance pynapple2)

# Create the configuration file with dynamic seeds populated
echo "; seeds" > "$CONFIG_FILE"
echo "seeds = [k8s:$PY1_POD, k8s:$PY2_POD, ssh:$PY1_INST, ssh:$PY2_INST]" >> "$CONFIG_FILE"
cat <<EOL >> "$CONFIG_FILE"
; core
timeout = 180
ssh-concurrency = 10
ssh-name-command = echo \$SANDBOX_APP_NAME
; aws provider
aws-app-name-tag = App
aws-tag-filters = [Environment=sandbox1]
; k8s provider
k8s-label-selectors = [environment=dev]
k8s-app-name-label = app
; export
export-ascii-verbose
EOL

echo "Discover command with seeds written to \`$CONFIG_FILE\`. Run \`astrolabe discover -c $CONFIG_FILE\` to execute!"

echo "$CONFIG_FILE contents:"
cat "$CONFIG_FILE"
