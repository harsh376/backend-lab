#!/usr/bin/env bash

set -euo pipefail

readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly repo_root="$(cd -- "${script_dir}/.." && pwd)"
readonly terraform_root="${repo_root}/infra/terraform"

usage() {
  cat <<'EOF'
Usage: bin/terraform.sh [--profile PROFILE] [--environment ENV] <command> [arguments]

Manage the repository's Terraform environments from any working directory.

Commands:
  account                         Show the active AWS identity
  bootstrap [environment]         Create the configured state bucket and initialize
  init [-e environment]           Initialize an environment (default: dev)
  fmt [-e environment]            Check Terraform formatting
  validate [-e environment]       Validate an environment
  check [-e environment]          Run fmt and validate
  plan [-e environment] [-- ARGS] Check and save <environment>.tfplan
  show [-e environment] [-- ARGS] Show the saved plan
  apply [-e environment] [-- ARGS] Apply the saved plan
  help                            Show this help

Examples:
  bin/terraform.sh bootstrap
  bin/terraform.sh plan
  bin/terraform.sh apply
  bin/terraform.sh plan --environment prod

The AWS profile defaults to AWS_PROFILE when set, otherwise m5-cli. Override it
with --profile PROFILE before the command. If Terraform fails, the wrapper
refreshes the SSO session and retries the Terraform command once.
The environment defaults to dev. Override it with --environment ENV (or -e)
before or after the command. A positional environment is also accepted.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is required but was not found."
}

set_environment() {
  environment="${1:-dev}"

  [[ "${environment}" =~ ^[[:alnum:]][[:alnum:]_-]*$ ]] || \
    die "Invalid environment name '${environment}'."

  environment_dir="${terraform_root}/environments/${environment}"
  [[ -d "${environment_dir}" ]] || \
    die "Terraform environment '${environment}' does not exist at ${environment_dir}."

  plan_file="${environment}.tfplan"
}

parse_environment() {
  if [[ $# -gt 0 && ( "$1" == "-e" || "$1" == "--environment" ) ]]; then
    [[ $# -ge 2 ]] || die "$1 requires an environment name."
    set_environment "$2"
    shift 2
  elif [[ $# -gt 0 && "$1" != -* ]]; then
    set_environment "$1"
    shift
  else
    set_environment "${default_environment}"
  fi

  if [[ "${1:-}" == "--" ]]; then
    shift
  fi

  remaining_args=("$@")
}

run_terraform() {
  require_command terraform
  if terraform -chdir="${environment_dir}" "$@"; then
    return
  fi

  authenticate_aws
  terraform -chdir="${environment_dir}" "$@"
}

show_account() {
  require_command aws
  if aws sts get-caller-identity --no-cli-pager; then
    return
  fi

  authenticate_aws
  aws sts get-caller-identity --no-cli-pager
}

authenticate_aws() {
  require_command aws
  echo "Refreshing AWS SSO credentials for profile '${AWS_PROFILE}'..."
  aws sso login
}

run_fmt() {
  run_terraform fmt -check
}

run_validate() {
  run_terraform validate
}

backend_config_file() {
  echo "${environment}.s3.tfbackend"
}

configured_state_bucket() {
  local backend_config
  local line

  backend_config="${environment_dir}/$(backend_config_file)"
  [[ -f "${backend_config}" ]] || \
    die "Backend configuration was not found at ${backend_config}."

  state_bucket=""
  while IFS= read -r line; do
    if [[ "${line}" =~ ^[[:space:]]*bucket[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
      state_bucket="${BASH_REMATCH[1]}"
      break
    fi
  done < "${backend_config}"

  [[ -n "${state_bucket}" ]] || \
    die "No bucket was configured in ${backend_config}."
}

bootstrap_state_bucket() {
  local aws_account_id
  local terraform_state_bucket="$1"
  local terraform_state_region="us-east-1"

  require_command aws

  # Fail before creating anything if the active AWS profile is not authenticated.
  aws_account_id="$(
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
}

run_init() {
  local backend_config
  backend_config="$(backend_config_file)"
  [[ -f "${environment_dir}/${backend_config}" ]] || \
    die "Backend configuration '${backend_config}' was not found in ${environment_dir}."
  run_terraform init -backend-config="${backend_config}"
}

aws_profile="${AWS_PROFILE:-m5-cli}"
default_environment="dev"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || die "--profile requires a profile name."
      aws_profile="$2"
      shift 2
      ;;
    -e|--environment)
      [[ $# -ge 2 ]] || die "$1 requires an environment name."
      default_environment="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

export AWS_PROFILE="${aws_profile}"

command_name="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${command_name}" in
  account)
    [[ $# -eq 0 ]] || die "account does not accept arguments."
    show_account
    ;;
  bootstrap)
    parse_environment "$@"
    [[ ${#remaining_args[@]} -eq 0 ]] || die "bootstrap only accepts an optional environment."
    show_account >/dev/null
    configured_state_bucket
    bootstrap_state_bucket "${state_bucket}"
    run_init
    ;;
  init)
    parse_environment "$@"
    [[ ${#remaining_args[@]} -eq 0 ]] || die "init only accepts an optional environment."
    run_init
    ;;
  fmt)
    parse_environment "$@"
    [[ ${#remaining_args[@]} -eq 0 ]] || die "fmt only accepts an optional environment."
    run_fmt
    ;;
  validate)
    parse_environment "$@"
    [[ ${#remaining_args[@]} -eq 0 ]] || die "validate only accepts an optional environment."
    run_validate
    ;;
  check)
    parse_environment "$@"
    [[ ${#remaining_args[@]} -eq 0 ]] || die "check only accepts an optional environment."
    run_fmt
    run_validate
    ;;
  plan)
    parse_environment "$@"
    run_fmt
    run_validate
    if [[ ${#remaining_args[@]} -eq 0 ]]; then
      run_terraform plan -out="${plan_file}"
    else
      run_terraform plan -out="${plan_file}" "${remaining_args[@]}"
    fi
    echo
    echo "Saved plan: ${environment_dir}/${plan_file}"
    echo "Review it with: bin/terraform.sh${aws_profile:+ --profile ${aws_profile}} show ${environment}"
    ;;
  show)
    parse_environment "$@"
    [[ -f "${environment_dir}/${plan_file}" ]] || \
      die "Saved plan '${environment_dir}/${plan_file}' does not exist; run the plan command first."
    if [[ ${#remaining_args[@]} -eq 0 ]]; then
      run_terraform show "${plan_file}"
    else
      run_terraform show "${remaining_args[@]}" "${plan_file}"
    fi
    ;;
  apply)
    parse_environment "$@"
    [[ -f "${environment_dir}/${plan_file}" ]] || \
      die "Saved plan '${environment_dir}/${plan_file}' does not exist; run and review the plan command first."
    if [[ ${#remaining_args[@]} -eq 0 ]]; then
      run_terraform apply "${plan_file}"
    else
      run_terraform apply "${remaining_args[@]}" "${plan_file}"
    fi
    ;;
  help)
    [[ $# -eq 0 ]] || die "help does not accept arguments."
    usage
    ;;
  *)
    usage >&2
    echo >&2
    die "Unknown command '${command_name}'."
    ;;
esac
