# Shiftly

Shiftly is a Django workforce scheduling and attendance application.

## Local development setup

The project uses Python 3.14.7 and PostgreSQL. Install PostgreSQL locally and make sure its service is running before starting Django.

From the project folder, create and activate a virtual environment in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create a local PostgreSQL database named `shiftly` (adjust the role name if your local PostgreSQL setup uses a different one):

```powershell
createdb -U postgres shiftly
```

Set the development environment and database connection in the same PowerShell window. Replace the example database credentials with your local PostgreSQL role and password:

```powershell
$env:DEBUG = "true"
$env:DATABASE_URL = "postgresql://postgres:your-password@localhost:5432/shiftly"
```

Apply database migrations and start Django's development server:

```powershell
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/signup/> to create the first employer workspace. PowerShell environment variables last only for the current window, so set `DEBUG` and `DATABASE_URL` again in a new one.

The root `requirements.txt` installs the shared application dependencies for development. The production-only Gunicorn dependency is kept in `requirements/production.txt`.
