# Terraform infrastructure

Terraform runs locally and stores its state in a private, versioned S3 bucket.
Native S3 lock files protect state-changing operations from concurrent writers.

## Prerequisites

- Terraform 1.10 or newer
- AWS CLI v2
- An authenticated AWS profile with permission to create and manage the state
  bucket and the application infrastructure

Set the profile for the current shell and verify the target AWS account before
running Terraform:

```bash
export AWS_PROFILE=m5-cli
aws sts get-caller-identity
```

Do not put AWS access keys in Terraform files, variable files, backend files, or
saved plan files.

## 1. Create the remote-state bucket

From the repository root, run the bootstrap script with a globally unique S3
bucket name:

```bash
./infra/terraform/bootstrap.sh my-app--dev--terraform-state
```

The script verifies the active AWS credentials, creates the bucket in
`us-east-1` with bucket-owner-enforced object ownership, and enables versioning.
New S3 buckets use server-side encryption and block public access by default.

The state bucket is intentionally provisioned outside Terraform so it does not
depend on the state it stores.

## 2. Initialize the development environment

```bash
cd infra/terraform/environments/dev
```

The committed `dev.s3.tfbackend` file references the bucket created above.
Because the bucket is dedicated to development, its state uses the simple
`terraform.tfstate` object key. Initialize and check the development root
module:

```bash
terraform init -backend-config=dev.s3.tfbackend
terraform fmt -check
terraform validate
terraform plan -out=dev.tfplan
```

Once the plan has been reviewed, apply that exact saved plan:

```bash
terraform apply dev.tfplan
```

Add production as another root module with its own S3 state key and more
restrictive AWS permissions rather than sharing the development state.

## Routine workflow

From the relevant environment directory:

```bash
terraform fmt -check
terraform validate
terraform plan -out=dev.tfplan
terraform show dev.tfplan
terraform apply dev.tfplan
```

Commit Terraform source files, backend configuration, and
`.terraform.lock.hcl`. Terraform generates the lock file during `init`; it pins
the selected provider versions and package checksums so installs are
reproducible across machines. Do not edit it manually. Do not commit state,
saved plans, or `.tfvars` files.
