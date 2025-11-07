output "alb_dns_name" { value = aws_lb.core.dns_name }
output "service_name" { value = aws_ecs_service.core.name }
output "cluster_id" { value = aws_ecs_cluster.core.id }