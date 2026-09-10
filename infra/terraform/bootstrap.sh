#!/usr/bin/env bash

set -euo pipefail

readonly terraform_state_region="us-east-1"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <globally-unique-s3-bucket-name>" >&2
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "Error: AWS CLI v2 is required but was not found." >&2
  exit 1
fi

readonly terraform_state_bucket="$1"

# Fail before creating anything if the active AWS profile is not authenticated.
readonly aws_account_id="$(
  aws sts get-caller-identity \
    --query Account \
    --output text \
    --no-cli-pager
)"

if aws s3api head-bucket \
  --bucket "${terraform_state_bucket}" \
  --region "${terraform_state_region}" \
  --expected-bucket-owner "${aws_account_id}" \
  --no-cli-pager 2>/dev/null; then
  echo "Bucket '${terraform_state_bucket}' already exists and is accessible."
else
  aws s3api create-bucket \
    --bucket "${terraform_state_bucket}" \
    --region "${terraform_state_region}" \
    --object-ownership BucketOwnerEnforced \
    --no-cli-pager
fi

aws s3api put-bucket-versioning \
  --bucket "${terraform_state_bucket}" \
  --region "${terraform_state_region}" \
  --expected-bucket-owner "${aws_account_id}" \
  --versioning-configuration Status=Enabled \
  --no-cli-pager

echo "Terraform state bucket '${terraform_state_bucket}' is ready in ${terraform_state_region}."
