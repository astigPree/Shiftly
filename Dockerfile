FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/production.txt \
    && groupadd --gid 10001 shiftly \
    && useradd --uid 10001 --gid shiftly --no-create-home shiftly
COPY --chown=shiftly:shiftly . .
RUN mkdir -p /app/staticfiles && chown shiftly:shiftly /app/staticfiles
USER shiftly
EXPOSE 8000
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "config.wsgi:application"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements/test.txt
USER shiftly
ENV DJANGO_SETTINGS_MODULE=config.test_settings
CMD ["python", "-m", "coverage", "run", "manage.py", "test", "tests", "--noinput"]
