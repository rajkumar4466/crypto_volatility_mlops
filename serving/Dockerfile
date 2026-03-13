FROM public.ecr.aws/lambda/python:3.11

# Install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt --no-cache-dir

# Copy application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/
# Copy Feast feature repo (feature_store.yaml + feature definitions)
COPY feature_repo/ ${LAMBDA_TASK_ROOT}/feature_repo/

# Lambda handler entrypoint (module.function)
CMD ["app.main.handler"]
