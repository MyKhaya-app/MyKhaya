#!/bin/sh
set -eu
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=migration_password="$MYKHAYA_MIGRATION_DB_PASSWORD" \
  --set=runtime_password="$MYKHAYA_DB_PASSWORD" <<-'SQL'
    CREATE ROLE mykhaya_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'migration_password';
    CREATE ROLE mykhaya_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'runtime_password';
    ALTER DATABASE mykhaya OWNER TO mykhaya_migrator;
    GRANT CONNECT ON DATABASE mykhaya TO mykhaya_app;
    GRANT USAGE ON SCHEMA public TO mykhaya_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mykhaya_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mykhaya_app;
SQL
