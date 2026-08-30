#!/bin/sh
# Drop from root to PUID:PGID before running the app.
#
# Mycelium writes .strm files into a directory that Jellyfin and Plex also read
# and delete from. Deleting a file needs write permission on its parent
# DIRECTORY, so all three have to agree on a user id. That id is a property of
# the deployment, not of the image, which is why it arrives as PUID/PGID at
# runtime rather than a USER line in the Dockerfile.
#
# PUID=0 (the default) keeps the historical behaviour exactly: run as root and
# touch nothing.
set -eu

PUID="${PUID:-0}"
PGID="${PGID:-0}"

if [ "$PUID" = "0" ] && [ "$PGID" = "0" ]; then
    exec "$@"
fi

if [ "$(id -u)" != "0" ]; then
    # Already non-root (someone set `user:` as well). We cannot chown or drop
    # privileges from here, so just run and let the app report any problem.
    echo "[entrypoint] Already running as uid $(id -u); ignoring PUID/PGID." >&2
    exec "$@"
fi

DB_FILE="${DB_PATH:-/data/requests.db}"
DATA_ROOT="$(dirname "$DB_FILE")"

# Every directory the app writes to. Deduplicated so a custom layout that
# points several of these at one place is not chowned repeatedly.
DIRS=""
for d in "$DATA_ROOT" "${MEDIA_PATH:-/data/media}" "${SPORE_MEDIA_PATH:-/data/plex-media}"; do
    case " $DIRS " in
        *" $d "*) ;;
        *) DIRS="$DIRS $d" ;;
    esac
done

for d in $DIRS; do
    [ -d "$d" ] || mkdir -p "$d" 2>/dev/null || true
done

# The marker carries the ids in its name, so changing PUID/PGID re-runs the
# recursive pass instead of silently leaving half the tree owned by the old id.
MARKER="$DATA_ROOT/.ownership-$PUID-$PGID"

if [ -e "$MARKER" ] && [ "${FORCE_CHOWN:-0}" != "1" ]; then
    # Fast path. A recursive chown over a large media tree takes minutes and
    # would run on every restart, so once the tree is correct only the mount
    # roots and the database files are re-checked.
    for d in $DIRS; do
        chown "$PUID:$PGID" "$d" 2>/dev/null || true
    done
    for f in "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"; do
        [ -e "$f" ] && chown "$PUID:$PGID" "$f" 2>/dev/null || true
    done
else
    echo "[entrypoint] Setting ownership of the data directories to $PUID:$PGID."
    echo "[entrypoint] This runs once and can take a few minutes on a large library."
    ok=1
    for d in $DIRS; do
        chown -R "$PUID:$PGID" "$d" || { ok=0; echo "[entrypoint] WARNING: could not chown $d" >&2; }
    done
    if [ "$ok" = "1" ]; then
        touch "$MARKER" 2>/dev/null && chown "$PUID:$PGID" "$MARKER" 2>/dev/null || true
        echo "[entrypoint] Ownership set."
    else
        echo "[entrypoint] WARNING: ownership is incomplete; not recording it as done." >&2
    fi
fi

# A passwd/group entry is not needed to run, but without one HOME is unset and
# anything calling getpwuid() (some libraries do) gets an error instead of a row.
if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" mycelium 2>/dev/null || true
fi
if ! getent passwd "$PUID" >/dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -M -d /app -s /usr/sbin/nologin mycelium 2>/dev/null || true
fi

echo "[entrypoint] Starting as $PUID:$PGID."
exec gosu "$PUID:$PGID" "$@"
