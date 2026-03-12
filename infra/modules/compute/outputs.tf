output "ec2_public_ip" {
  description = "Public IP of the Airflow EC2 instance"
  value       = aws_instance.airflow.public_ip
}

output "ec2_instance_id" {
  description = "EC2 instance ID of the Airflow host"
  value       = aws_instance.airflow.id
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint hostname"
  value       = aws_db_instance.airflow_metadata.address
}

output "rds_port" {
  description = "RDS PostgreSQL port"
  value       = aws_db_instance.airflow_metadata.port
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint hostname"
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_cluster.redis.port
}
