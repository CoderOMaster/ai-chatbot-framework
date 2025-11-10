import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_env_example_contains_expected_keys():
    content = read("ai-chatbot-framework/app/common/.env.example")
    # Ensure core Mongo settings are present
    assert "MONGODB_HOST=" in content
    assert "MONGODB_DATABASE=" in content
    # Optional credentials keys present (may be empty)
    assert "MONGODB_USERNAME=" in content
    assert "MONGODB_PASSWORD=" in content
    # Pool size and timeouts
    assert "MONGODB_MAX_POOL_SIZE=" in content
    assert "MONGODB_CONNECT_TIMEOUT_MS=" in content
    assert "MONGODB_SERVER_SELECTION_TIMEOUT_MS=" in content
    assert "MONGODB_SOCKET_TIMEOUT_MS=" in content


def test_terraform_secrets_module_defines_secret_and_outputs():
    main_tf = read("infra/terraform/mongodb-secrets/main.tf")
    variables_tf = read("infra/terraform/mongodb-secrets/variables.tf")
    outputs_tf = read("infra/terraform/mongodb-secrets/outputs.tf")

    # Resource definitions
    assert "aws_secretsmanager_secret\" \"mongodb_credentials\"" in main_tf
    assert "aws_secretsmanager_secret_version\" \"mongodb_credentials_version\"" in main_tf

    # Secret JSON structure contains expected fields
    expected_fields = ["host", "port", "username", "password", "database"]
    for f in expected_fields:
        assert f in main_tf

    # Variables
    assert "variable \"region\"" in variables_tf
    assert "variable \"secret_name_prefix\"" in variables_tf

    # Outputs
    assert "output \"secrets_arn\"" in outputs_tf
    assert "mongodb_credentials.arn" in outputs_tf