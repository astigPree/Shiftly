import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "90"))
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
capture_output = True
# Django trusts the scheme set by our private Nginx proxy. Gunicorn's listener
# is never published to the host; Nginx overwrites client forwarded headers.
forwarded_allow_ips = "*"
