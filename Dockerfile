FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd -g 10001 spp && \
    useradd -u 10001 -g spp -m -s /bin/bash spp

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY db /app/db
COPY policy /app/policy
COPY specs /app/specs
COPY app /app/app

RUN chown -R spp:spp /app

USER 10001:10001

ENV SPP_CP_REPO_ROOT=/app \
    PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
