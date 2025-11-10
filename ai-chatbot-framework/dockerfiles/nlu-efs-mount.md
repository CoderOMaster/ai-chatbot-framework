Mounting model artifacts for NLU services

Options
- EFS: Create an EFS filesystem and mount it to your ECS tasks or EC2 instances at /models.
- EBS/Host Path: For single-node or dev setups, bind mount a host directory.
- S3: Store artifacts in S3 and sync to /models at container start (e.g., aws s3 sync s3://bucket/path /models).

Permissions and IAM
- Grant ECS task role permissions to read/write the S3 bucket if using S3.
- For EFS, configure access points with appropriate POSIX UID/GID and security groups.

ENV
- MODEL_DIR=/models
- SPACY_LANG_MODEL=xx_core_web_sm