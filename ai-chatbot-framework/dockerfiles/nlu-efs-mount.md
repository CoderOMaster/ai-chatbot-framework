# Mounting model artifacts for NLU services

You can store trained model artifacts on a shared persistent volume so both the runtime and the trainer can access them.

Options:
- AWS EFS mounted to ECS/EKS tasks at /models
- EBS volume for EC2/EKS nodes
- S3 bucket sync to /models on container start (e.g., aws s3 sync s3://bucket/path /models)

Set env:
- MODEL_DIR=/models
- SPACY_LANG_MODEL=xx_core_web_sm (or your custom model name)

IAM/Permissions:
- For EFS, attach access point and security groups to tasks.
- For S3, grant GetObject/ListObject permissions to the path storing models.

Ensure appropriate POSIX permissions on mounted path so container user can read/write.