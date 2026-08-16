# One image, three roles: api, worker, migrate. The CMD is set per compose service.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vibelive/ ./vibelive/
COPY migrations/ ./migrations/

EXPOSE 8000
CMD ["uvicorn", "vibelive.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
