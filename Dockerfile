FROM python:3.13-slim
WORKDIR /app
COPY . .
RUN mkdir -p /app/data
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8080
CMD ["python","server.py"]
