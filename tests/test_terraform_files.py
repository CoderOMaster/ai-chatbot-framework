import os
from importlib import util


def test_terraform_variables_present():
    content = open('infra/terraform/mongodb-secrets/variables.tf').read()
    assert 'variable "mongodb_host"' in content
    assert 'variable "mongodb_database"' in content


def test_env_example_contains_keys():
    content = open('app/common/.env.example').read()
    assert 'MONGODB_HOST' in content
    assert 'MONGODB_DATABASE' in content