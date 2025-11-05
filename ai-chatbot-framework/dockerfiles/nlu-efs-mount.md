# Mounting models via EFS or S3

You can mount model artifacts into the container using EFS (NFS) or pull from S3 at startup.

- EFS: Create an AWS EFS file system and mount it to /models in your ECS task or docker-compose host mount. Ensure the IAM role (or EC2 instance) has necessary NFS access and security group rules.
- S3: Use a startup script to sync s3://your-bucket/models to /models using aws-cli. Ensure IAM role has s3:GetObject permissions.

Set MODEL_DIR environment variable to override default /models.