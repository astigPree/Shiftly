# Shiftly

Shiftly is a Django workforce scheduling and attendance application.

## Local development setup

The project is pinned to Python 3.9.13. Local development uses SQLite, so you do not need to install or configure PostgreSQL. Python 3.9 and Django 4.2 are both past security support, so use this compatibility setup for local development only, not production.

If you already have a Python 3.9 virtual environment active, you can update its packages directly. Otherwise, create a project environment in Command Prompt:

```cmd
py -3.9 -m venv .venv
.venv\Scripts\activate.bat
```

Confirm that `python --version` reports Python 3.9, then install the development dependencies:

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set development mode in the same Command Prompt window. Django will create and use the ignored `db.sqlite3` file in the project directory:

```cmd
set DEBUG=true
```

Apply database migrations and start Django's development server:

```cmd
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/signup/> to create the first employer workspace. Command Prompt environment variables last only for the current window, so set `DEBUG` again in a new one. Production remains configured for PostgreSQL through `DATABASE_URL`.

The root `requirements.txt` installs the shared application dependencies for development. The PostgreSQL adapter and Gunicorn are kept in `requirements/production.txt`.
