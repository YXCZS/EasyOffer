# EasyOffer database migrations

Run from `backend/`:

```text
alembic upgrade head
alembic downgrade -1
```

For an existing database created by the legacy SQL/bootstrap code, verify the
schema first and then run `alembic stamp 0001_initial_schema`. Do not run a
destructive downgrade against production without a backup.
