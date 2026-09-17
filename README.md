# Field Operations

Standalone Django/Railway deployment for proprietary field preinspection and
route planning. This project owns its users, workspaces, imports, routes, and
audit history. It does not connect to the OpenSkagit database.

## Local development

```powershell
copy .env.example .env
# Set DATABASE_URL to a local PostgreSQL/PostGIS database.
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The application calls OpenSkagit only through `OPENSKAGIT_API_URL` using the
server-to-server `OPENSKAGIT_API_TOKEN`. County ArcGIS, Cyclomedia, and
Valhalla are configured independently.

## Roles

- Regular authenticated users own private workspaces.
- Staff users can use the route planner and read-only team oversight screens.
- Superusers manage users and product configuration through `/admin/`.

## Railway

Create a separate Railway project with a separate PostgreSQL/PostGIS service.
Set `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and
the external service variables before deploying.
