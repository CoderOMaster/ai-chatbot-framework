from pathlib import Path


def test_terraform_frontend_module_contains_expected_resources():
    p = Path("infra/terraform/frontend/main.tf")
    assert p.exists(), "infra/terraform/frontend/main.tf should exist"
    content = p.read_text()

    # Ensure AWS provider and required resources are declared
    assert "required_providers" in content
    assert "resource \"aws_s3_bucket\" \"frontend_static_bucket\"" in content
    assert "resource \"aws_cloudfront_distribution\" \"frontend_cdn\"" in content

    # Ensure variables are referenced
    assert "var.bucket_name" in content
    assert "var.aws_region" in content

    # CloudFront defaults
    assert "default_root_object = \"index.html\"" in content
    assert "cloudfront_default_certificate = true" in content