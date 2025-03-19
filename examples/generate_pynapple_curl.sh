#!/bin/bash

# Function to retrieve the actual DNS name of the EC2 load balancer for pynapple1
get_ec2_lb_dns() {
    # Try classic ELB first
    local dns=$(aws elb describe-load-balancers \
        --output text | grep -i pynapple1 | head -n 1 | awk '{print $3}')
        
    # If not found, try v2 load balancers (ALB/NLB)
    if [ -z "$dns" ]; then
        dns=$(aws elbv2 describe-load-balancers \
            --output text | grep -i pynapple1 | head -n 1 | awk '{print $4}')
    fi
    
    # If still not found, try listing all load balancers and grep
    if [ -z "$dns" ]; then
        echo "Trying detailed search for pynapple1 load balancer..."
        aws elb describe-load-balancers --output text > /tmp/elbs.txt
        dns=$(grep -i pynapple1 /tmp/elbs.txt | head -n 1 | awk '{print $3}')
        
        if [ -z "$dns" ]; then
            aws elbv2 describe-load-balancers --output text > /tmp/elbv2s.txt
            dns=$(grep -i pynapple1 /tmp/elbv2s.txt | head -n 1 | awk '{print $4}')
        fi
    fi
    
    echo "$dns"
}

# Function to retrieve the actual DNS name of the K8s service load balancer for pynapple1
get_k8s_lb_dns() {
    kubectl get svc -o wide | grep pynapple1 | grep LoadBalancer | awk '{print $4}'
}

# Get the actual DNS names from the load balancers
EC2_LB=$(get_ec2_lb_dns)
K8S_LB=$(get_k8s_lb_dns)

# Check if we got valid DNS names
if [ -z "$EC2_LB" ]; then
    echo "Error: Could not find EC2 load balancer for pynapple1"
    exit 1
fi

if [ -z "$K8S_LB" ]; then
    echo "Error: Could not find K8s service load balancer for pynapple1"
    exit 1
fi

# Generate the curl command with the actual ELB DNS names
CURL_CMD="while true; do curl -v http://$EC2_LB/pynapples; echo -e '\n---\n'; curl -v http://$K8S_LB/pynapples; echo -e '\n==========\n'; sleep 5; done"

# Print the command
echo "Generated curl command:"
echo "$CURL_CMD"

# Also write to a file for easy execution
SCRIPT_FILE="$(dirname "$0")/pynapple-curl.sh"
echo '#!/bin/bash' > "$SCRIPT_FILE"
echo "$CURL_CMD" >> "$SCRIPT_FILE"
chmod +x "$SCRIPT_FILE"

echo "Script written to $SCRIPT_FILE. Run it with:"
echo "./$SCRIPT_FILE"

# Offer to execute the command directly
echo "Or execute it now? [y/N]"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo "Executing curl command..."
    eval "$CURL_CMD"
fi
