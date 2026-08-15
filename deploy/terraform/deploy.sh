#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "   BuildWise Capstone — Automated t3.small AWS Provisioner  "
echo "============================================================"
echo ""

# Check AWS CLI credentials
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "[!] Error: AWS CLI credentials not found or invalid."
    echo "    Please run 'aws configure' first or set AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY."
    exit 1
fi

echo "[✓] AWS CLI Credentials Verified!"
echo "[+] Initializing Terraform..."
terraform init -upgrade

echo "[+] Planning t3.small deployment..."
terraform plan -out=tfplan

echo ""
echo "============================================================"
echo "  Ready to provision t3.small EC2 Instance in AWS."
echo "============================================================"
read -p "Do you want to apply these changes now? (y/n): " CONFIRM

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "[+] Applying Terraform Plan..."
    terraform apply tfplan
    echo ""
    echo "============================================================"
    echo "  SUCCESS! BuildWise is being deployed to EC2."
    echo "  Allow ~2-3 minutes for containers to finish building."
    echo "============================================================"
    terraform output
else
    echo "Deployment cancelled."
fi
