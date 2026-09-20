# Shiftly

Shiftly is a Django workforce scheduling and attendance application.

## Local development setup

The project is pinned to Python 3.9.13 and PostgreSQL. Python 3.9 and Django 4.2 are both past security support, so use this compatibility setup for local development only, not production.

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

Create a local PostgreSQL database named `shiftly` (adjust the role name if your local PostgreSQL setup uses a different one):

```cmd
createdb -U postgres shiftly
```

Set the development environment and database connection in the same Command Prompt window. Replace the example database credentials with your local PostgreSQL role and password:

```cmd
set DEBUG=true
set DATABASE_URL=postgresql://postgres:your-password@localhost:5432/shiftly
```

Apply database migrations and start Django's development server:

```cmd
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/signup/> to create the first employer workspace. Command Prompt environment variables last only for the current window, so set `DEBUG` and `DATABASE_URL` again in a new one.

The root `requirements.txt` installs the shared application dependencies for development. The production-only Gunicorn dependency is kept in `requirements/production.txt`.
