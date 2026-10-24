FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bookrag_cloud ./bookrag_cloud
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "bookrag_cloud.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
