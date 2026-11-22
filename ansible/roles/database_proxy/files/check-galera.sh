#!/bin/sh
set -eu

status=$(/usr/bin/mariadb --defaults-extra-file=/etc/haproxy/galera-client.cnf \
    --host="$3" --port="$4" --batch --skip-column-names \
    --execute="SHOW GLOBAL STATUS WHERE Variable_name IN ('wsrep_ready','wsrep_local_state','wsrep_cluster_status'); SELECT @@global.read_only")

printf '%s\n' "$status" | /usr/bin/awk '
    $1 == "wsrep_ready" && $2 == "ON" { ready = 1 }
    $1 == "wsrep_local_state" && $2 == "4" { synced = 1 }
    $1 == "wsrep_cluster_status" && $2 == "Primary" { primary = 1 }
    NF == 1 && $1 == "0" { writable = 1 }
    END { exit !(ready && synced && primary && writable) }
'
