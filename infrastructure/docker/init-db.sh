#!/bin/sh
# MyKhaya PostgreSQL bootstrap: creates the migration and runtime roles.
#
# The postgres image runs this once, on the first start of an empty data
# directory; an existing volume skips /docker-entrypoint-initdb.d entirely, so
# nothing here can change an initialised database. The image sources this file
# from its bash entrypoint (it is not executable), so it is written for both
# sh and bash, prefixes every name it defines and cleans up after itself.
#
# Passwords (MK-SEC-001 v1.2, SEC-086a bootstrap): each comes from exactly one
# of MYKHAYA_<NAME> (legacy literal) or MYKHAYA_<NAME>_FILE (file secret under
# /run/secrets). A file is validated exactly as the application's hardened
# reader validates it (apps/api/mykhaya/secret_files.py), so the database and
# the application always see the same bytes. The superuser password
# (POSTGRES_PASSWORD / POSTGRES_PASSWORD_FILE) is the image's own: it reads it
# and passes it to initdb through a file descriptor.
#
# Passwords never appear in command-line arguments: they are written to psql's
# standard input by shell builtins, set as psql variables and quoted by psql.
# Statement logging and activity tracking are switched off for this session
# and psql reports errors tersely, so no log, trace or error repeats the
# statement text. Messages name variables and failure categories only.
set -eu

mykhaya_init_fail() {
  printf 'init-db: %s\n' "$1" >&2
  exit 1
}

mykhaya_nl=$(printf '\nx')
mykhaya_nl=${mykhaya_nl%x}
mykhaya_cr=$(printf '\r')

# Strict UTF-8 (no overlong forms, surrogates or values above U+10FFFF), the
# same acceptance as Python's decoder. Bytes arrive as decimal numbers on stdin.
mykhaya_is_utf8() {
  od -An -v -tu1 | awk '
    { for (i = 1; i <= NF; i++) { b = $i + 0
        if (need == 0) {
          if (b < 128) continue
          lo = 128; hi = 191
          if (b >= 194 && b <= 223) need = 1
          else if (b == 224) { need = 2; lo = 160 }
          else if ((b >= 225 && b <= 236) || b == 238 || b == 239) need = 2
          else if (b == 237) { need = 2; hi = 159 }
          else if (b == 240) { need = 3; lo = 144 }
          else if (b >= 241 && b <= 243) need = 3
          else if (b == 244) { need = 3; hi = 143 }
          else { bad = 1; exit }
        } else {
          if (b < lo || b > hi) { bad = 1; exit }
          need--; lo = 128; hi = 191
        }
    } }
    END { exit (bad || need) ? 1 : 0 }'
}

# Sets mykhaya_init_value from the file named by $2 (reported as $1).
mykhaya_read_secret_file() {
  mykhaya_name=$1
  mykhaya_path=$2
  case $mykhaya_path in
    /run/secrets/?*) ;;
    *) mykhaya_init_fail "$mykhaya_name is outside the approved secret locations" ;;
  esac
  case $mykhaya_path in
    *//* | */./* | */../* | */. | */.. | */)
      mykhaya_init_fail "$mykhaya_name must be a normalised path without '.' or '..'" ;;
  esac
  mykhaya_prefix=$mykhaya_path
  while [ -n "$mykhaya_prefix" ]; do
    [ -L "$mykhaya_prefix" ] && mykhaya_init_fail "$mykhaya_name path contains a symbolic link"
    mykhaya_prefix=${mykhaya_prefix%/*}
  done
  [ -e "$mykhaya_path" ] || mykhaya_init_fail "$mykhaya_name is missing"
  [ -f "$mykhaya_path" ] || mykhaya_init_fail "$mykhaya_name is not a regular file"
  [ -r "$mykhaya_path" ] || mykhaya_init_fail "$mykhaya_name is not readable (permission denied)"
  # Every later read reopens the same file through this descriptor, so the
  # path cannot be swapped once it has been checked.
  exec 9<"$mykhaya_path" || mykhaya_init_fail "$mykhaya_name could not be opened"
  mykhaya_fd=/proc/$$/fd/9
  [ "$(stat -L -c %F "$mykhaya_fd")" = "regular file" ] ||
    mykhaya_init_fail "$mykhaya_name is not a regular file"
  [ "$(stat -L -c %s "$mykhaya_fd")" -le 4096 ] || mykhaya_init_fail "$mykhaya_name is too large"
  mykhaya_bytes=$(head -c 4097 <"$mykhaya_fd" | wc -c)
  [ "$mykhaya_bytes" -le 4096 ] || mykhaya_init_fail "$mykhaya_name is too large"
  [ "$(head -c 4096 <"$mykhaya_fd" | tr -d '\000' | wc -c)" -eq "$mykhaya_bytes" ] ||
    mykhaya_init_fail "$mykhaya_name contains a NUL byte"
  head -c 4096 <"$mykhaya_fd" | mykhaya_is_utf8 || mykhaya_init_fail "$mykhaya_name is not valid UTF-8"
  mykhaya_init_value=$(head -c 4096 <"$mykhaya_fd"; printf x)
  exec 9<&-
  mykhaya_init_value=${mykhaya_init_value%x}
  mykhaya_init_value=${mykhaya_init_value%"$mykhaya_nl"}
  mykhaya_init_value=${mykhaya_init_value%"$mykhaya_cr"}
  case $mykhaya_init_value in
    *"$mykhaya_nl"* | *"$mykhaya_cr"*) mykhaya_init_fail "$mykhaya_name must contain a single line" ;;
    "") mykhaya_init_fail "$mykhaya_name is empty" ;;
    [[:space:]]* | *[[:space:]])
      mykhaya_init_fail "$mykhaya_name must not have leading or trailing whitespace" ;;
  esac
}

# Sets mykhaya_init_value from MYKHAYA_<$1> or MYKHAYA_<$1>_FILE (exactly one).
# eval only ever sees these fixed variable names, never a value.
mykhaya_password() {
  eval "mykhaya_literal=\${MYKHAYA_$1-}"
  eval "mykhaya_file=\${MYKHAYA_$1_FILE-}"
  if [ -n "$mykhaya_literal" ] && [ -n "$mykhaya_file" ]; then
    mykhaya_init_fail "Set MYKHAYA_$1 or MYKHAYA_$1_FILE, not both"
  elif [ -n "$mykhaya_file" ]; then
    mykhaya_read_secret_file "MYKHAYA_$1_FILE" "$mykhaya_file"
  elif [ -n "$mykhaya_literal" ]; then
    mykhaya_init_value=$mykhaya_literal
  else
    mykhaya_init_fail "MYKHAYA_$1 or MYKHAYA_$1_FILE is required"
  fi
  mykhaya_literal=
}

# psql single-quoted meta-command argument: double quotes and backslashes.
mykhaya_psql_quote() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/''/g"
}

mykhaya_password MIGRATION_DB_PASSWORD
mykhaya_migration_quoted=$(mykhaya_psql_quote "$mykhaya_init_value")
mykhaya_password DB_PASSWORD
mykhaya_runtime_quoted=$(mykhaya_psql_quote "$mykhaya_init_value")
mykhaya_init_value=

{
  printf '%s\n' \
    "SET log_statement = 'none';" \
    "SET log_min_error_statement = 'panic';" \
    "SET log_min_duration_statement = -1;" \
    "SET track_activities = off;" \
    '\set VERBOSITY terse' \
    '\set SHOW_CONTEXT never'
  printf "\\\\set migration_password '%s'\n" "$mykhaya_migration_quoted"
  printf "\\\\set runtime_password '%s'\n" "$mykhaya_runtime_quoted"
  cat <<'SQL'
CREATE ROLE mykhaya_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'migration_password';
CREATE ROLE mykhaya_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'runtime_password';
ALTER DATABASE mykhaya OWNER TO mykhaya_migrator;
GRANT CONNECT ON DATABASE mykhaya TO mykhaya_app;
GRANT USAGE ON SCHEMA public TO mykhaya_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mykhaya_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mykhaya_app;
SQL
} | PGCLIENTENCODING=UTF8 psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"

mykhaya_migration_quoted=
mykhaya_runtime_quoted=
unset mykhaya_migration_quoted mykhaya_runtime_quoted mykhaya_init_value mykhaya_literal \
  mykhaya_file mykhaya_name mykhaya_path mykhaya_prefix mykhaya_fd mykhaya_bytes
