# Root module — calls all 5 sub-modules
# Apply order enforced by spin_up.sh:
#   1. module.billing (billing alarm first — non-negotiable)
#   2. module.network + module.storage (infrastructure base)
#   3. push_stub_image.sh (ECR must have an image before Lambda apply)
#   4. module.compute + module.serverless

module "billing" {
  source = "./modules/billing"

  project_name = var.project_name
  alert_email  = var.alert_email

  providers = {
    aws.billing = aws.billing
  }
}

module "network" {
  source = "./modules/network"

  project_name = var.project_name
  aws_region   = var.aws_region
}

module "storage" {
  source = "./modules/storage"

  project_name = var.project_name
}

module "compute" {
  source = "./modules/compute"

  project_name       = var.project_name
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  airflow_sg_id      = module.network.airflow_sg_id
  rds_sg_id          = module.network.rds_sg_id
  redis_sg_id        = module.network.redis_sg_id
  key_name           = var.ec2_key_name
  db_username        = var.db_username
  db_password        = var.db_password
}

module "serverless" {
  source = "./modules/serverless"

  project_name        = var.project_name
  ecr_repository_url  = module.storage.ecr_repository_url
  private_subnet_ids  = module.network.private_subnet_ids
  lambda_sg_id        = module.network.lambda_sg_id
  redis_endpoint      = module.compute.redis_endpoint
  s3_bucket_name      = module.storage.s3_bucket_name
  s3_bucket_arn       = module.storage.s3_bucket_arn
  dynamodb_table_arn  = module.storage.dynamodb_table_arn
  dynamodb_table_name = module.storage.dynamodb_table_name
}
