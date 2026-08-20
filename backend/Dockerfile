FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY alembic ./alembic

# Run unprivileged: many clusters reject root containers outright, and nothing
# here needs write access outside /tmp.
RUN useradd --create-home --uid 10001 zbridge && chown -R zbridge:zbridge /app
USER 10001

# Migrations are NOT run here on purpose: with more than one replica two
# processes would race on the same database. See the `migrate` compose service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
