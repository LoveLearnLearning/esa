FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./email_service

USER 65532:65532
EXPOSE 8080
CMD ["uvicorn", "email_service.app:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
uvicorn email_service.app:create_app_from_env --factory --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips 127.0.0.1
