FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY app/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/backend/app ./app
# Raw datasets are deliberately ignored by Git. They are supplied locally before
# docker compose build, then converted to a small runtime artifact in this image.
RUN python -m app.prepare_data \
  --support app/data/raw/customer_support_tickets.csv \
  --classifier app/data/raw/all_tickets_processed_improved_v3.csv \
  --churn-dir app/data/raw/churn
# Copied after the data build so UI-only changes do not retrain the models.
COPY --from=frontend /frontend/dist ./app/static
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
