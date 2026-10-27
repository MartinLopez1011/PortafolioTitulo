FROM public.ecr.aws/lambda/python:3.12

# lightgbm requiere libgomp en Amazon Linux 2023
RUN dnf install -y libgomp && dnf clean all

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY artifacts/ ${LAMBDA_TASK_ROOT}/artifacts/
COPY app/ ${LAMBDA_TASK_ROOT}/app/

CMD [ "app.lambda_function.lambda_handler" ]