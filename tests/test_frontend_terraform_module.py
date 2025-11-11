from pathlib import Path

MAIN_TF = Path("infra/terraform/frontend/main.tf")
VARS_TF = Path("infra/terraform/frontend/variables.tf")


def test_terraform_files_exist():
    assert MAIN_TF.exists(), "infra/terraform/frontend/main.tf should exist"
    assert VARS_TF.exists(), "infra/terraform/frontend/variables.tf should exist"


def test_main_tf_includes_s3_and_optional_website_and_cdn():
    src = MAIN_TF.read_text(encoding="utf-8")

    # Provider block for AWS
    assert "required_providers" in src and "hashicorp/aws" in src
    assert "provider \"aws\"" in src and "region = var.region" in src

    # S3 bucket resource
    assert 'resource "aws_s3_bucket" "frontend_static_bucket"' in src

    # Optional website configuration controlled by enable_static_hosting
    assert 'resource "aws_s3_bucket_website_configuration" "frontend_website"' in src
    assert 'count  = var.enable_static_hosting ? 1 : 0' in src

    # Optional CloudFront distribution controlled by enable_cdn
    assert 'resource "aws_cloudfront_distribution" "frontend_cdn"' in src
    assert 'count = var.enable_cdn ? 1 : 0' in src

    # Basic distribution settings
    assert 'default_root_object = "index.html"' in src
    assert 'viewer_protocol_policy = "redirect-to-https"' in src


def test_variables_tf_definitions():
    src = VARS_TF.read_text(encoding="utf-8")

    # region variable
    assert 'variable "region"' in src
    assert 'type        = string' in src
    assert 'default     = "us-east-1"' in src

    # bucket_name variable
    assert 'variable "bucket_name"' in src
    assert 'type        = string' in src

    # enable_static_hosting variable
    assert 'variable "enable_static_hosting"' in src
    assert 'type        = bool' in src
    assert 'default     = true' in src

    # enable_cdn variable
    assert 'variable "enable_cdn"' in src
    assert 'type        = bool' in src
    assert 'default     = true' in src