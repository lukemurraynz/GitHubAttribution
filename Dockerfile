FROM python:3.14-slim
WORKDIR /app
COPY . /app
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "copilot_cost.service.server"]
