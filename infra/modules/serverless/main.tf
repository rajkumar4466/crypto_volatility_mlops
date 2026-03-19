# Serverless module — Lambda predictor, API Gateway HTTP API, SNS drift topic
# Lambda uses x86_64 ONLY — ARM64 has ONNX Runtime illegal instruction bug (STATE.md decision)

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# IAM Role for Lambda
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Name    = "${var.project_name}-lambda-role"
    Project = var.project_name
  }
}

# Attach VPC execution policy
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# S3 read policy for Lambda
resource "aws_iam_role_policy" "lambda_s3_read" {
  name = "${var.project_name}-lambda-s3-read"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [var.s3_bucket_arn, "${var.s3_bucket_arn}/*"]
    }]
  })
}

# DynamoDB write policy for Lambda
resource "aws_iam_role_policy" "lambda_dynamodb_write" {
  name = "${var.project_name}-lambda-dynamodb-write"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:Scan", "dynamodb:Query"]
      Resource = [var.dynamodb_table_arn]
    }]
  })
}

# Lambda function — predictor stub (image pushed by push_stub_image.sh before apply)
resource "aws_lambda_function" "predictor" {
  function_name = "${var.project_name}-predictor"
  role          = aws_iam_role.lambda.arn

  package_type  = "Image"
  image_uri     = "${var.ecr_repository_url}:latest"
  architectures = ["x86_64"] # NOT arm64 — ONNX Runtime ARM64 illegal instruction bug

  memory_size = 512
  timeout     = 60

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_sg_id]
  }

  environment {
    variables = {
      REDIS_HOST        = var.redis_endpoint
      REDIS_PORT        = "6379"
      S3_BUCKET         = var.s3_bucket_name
      PREDICTIONS_TABLE = var.dynamodb_table_name
      MODEL_VERSION     = "0.0.0" # Updated by Phase 3 CI on promotion
      FEAST_REPO_PATH   = "/var/task/feature_repo"
    }
  }

  tags = {
    Name    = "${var.project_name}-predictor"
    Project = var.project_name
  }
}

# API Gateway HTTP API (v2) — cheaper and simpler than REST API (v1)
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"

  tags = {
    Name    = "${var.project_name}-api"
    Project = var.project_name
  }
}

# API Gateway Stage (auto-deploy) with rate limiting
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Default throttle for all routes
  default_route_settings {
    throttling_burst_limit = 10   # max concurrent requests
    throttling_rate_limit  = 5    # requests per second (sustained)
  }

  # Per-route throttle for /predict (tighter than default)
  route_settings {
    route_key              = "GET /predict"
    throttling_burst_limit = 5    # max 5 concurrent predict calls
    throttling_rate_limit  = 2    # max 2 predictions per second
  }
}

# Lambda integration
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.predictor.invoke_arn
  payload_format_version = "2.0"
}

# Routes
resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "predict" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /predict"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Permission for API Gateway to invoke Lambda
resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.predictor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# Backfill Lambda function — triggered by EventBridge Scheduler every 30 min
resource "aws_lambda_function" "backfill" {
  function_name = "${var.project_name}-backfill"
  role          = aws_iam_role.lambda.arn

  package_type  = "Image"
  image_uri     = "${var.ecr_repository_url}:backfill-latest"
  architectures = ["x86_64"]

  memory_size = 256
  timeout     = 120 # 2 minutes — scan + CoinGecko calls

  environment {
    variables = {
      PREDICTIONS_TABLE = var.dynamodb_table_name
    }
  }

  tags = {
    Name    = "${var.project_name}-backfill"
    Project = var.project_name
  }
}

# IAM Role for EventBridge Scheduler to invoke Lambda
resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "${var.project_name}-scheduler-invoke"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.backfill.arn
    }]
  })
}

# EventBridge Scheduler — invoke backfill Lambda every 30 minutes
resource "aws_scheduler_schedule" "backfill" {
  name       = "${var.project_name}-backfill-schedule"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(30 minutes)"

  target {
    arn      = aws_lambda_function.backfill.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

# SNS topic for data drift alerts (separate from billing topic)
resource "aws_sns_topic" "drift_alerts" {
  name = "${var.project_name}-drift-alerts"

  tags = {
    Name    = "${var.project_name}-drift-alerts"
    Project = var.project_name
  }
}
