output "efs_id" { value = aws_efs_file_system.nlu_models.id }
output "ecs_task_definition_arn" { value = aws_ecs_task_definition.nlu_runtime.arn }
output "ecs_service_name" { value = aws_ecs_service.nlu_runtime.name }