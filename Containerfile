FROM docker.io/library/python:3.12-slim
WORKDIR /app
COPY app.py .
ENV ERP_BIND=0.0.0.0 PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
EXPOSE 8080
CMD ["python", "-u", "app.py"]
