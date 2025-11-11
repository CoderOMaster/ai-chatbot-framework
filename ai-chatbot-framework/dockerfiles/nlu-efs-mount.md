NLU model artifacts via external storage

Options:
- EFS/EBS mounted to containers at /models
- S3 bucket sync to local /models on start

EFS notes:
- Create aws_efs_file_system and mount targets in your VPC
- Ensure ECS task role has permissions for EFS if using access points
- In task definition, mount EFS to container path /models (read-only for runtime)

S3 notes:
- Grant task role s3:GetObject to the model bucket/prefix
- On container start, run an init that syncs to /models or use s3fs-fuse

Permissions:
- Runtime should have read-only to model path
- Trainer needs read-write to produce new model versions