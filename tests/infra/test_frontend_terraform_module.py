from pathlib import Path


MAIN = Path("infra/terraform/frontend/main.tf")
VARS = Path("infra/terraform/frontend/variables.tf")
OUTS = Path("infra/terraform/frontend/outputs.tf")


def test_frontend_terraform_files_exist():
    assert MAIN.exists()
    assert VARS.exists()
    assert OUTS.exists()


def test_main_tf_includes_s3_and_cloudfront_with_oac():
    content = MAIN.read_text(encoding="utf-8")
    # S3 bucket and access block
    assert "resource \"aws_s3_bucket\" \"frontend_static_bucket\"" in content
    assert "resource \"aws_s3_bucket_public_access_block\" \"this\"" in content

    # CloudFront OAC and distribution
    assert "resource \"aws_cloudfront_origin_access_control\" \"oac\"" in content
    assert "resource \"aws_cloudfront_distribution\" \"frontend_cdn\"" in content
    assert "origin_access_control_id" in content
    assert "cloudfront_default_certificate = true" in content


def test_variables_and_outputs_are_defined():
    v = VARS.read_text(encoding="utf-8")
    assert "variable \"region\"" in v
    assert "variable \"bucket_name\"" in v
    assert "variable \"force_destroy\"" in v

    o = OUTS.read_text(encoding="utf-8")
    assert "output \"bucket_id\"" in o
    assert "output \"cloudfront_domain\"" in o