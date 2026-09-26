"""Run migrations/static collection once, before starting web workers."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
from django.core.management import call_command

django.setup()
call_command("migrate", interactive=False)
call_command("collectstatic", interactive=False, clear=True)
