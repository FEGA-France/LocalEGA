#!/usr/bin/env ash

set -e

umask 0077

mkdir -p -m 2700 ${HOME}/.config/rc
cat > ${HOME}/.config/rc/config.toml <<EOF
schema_version = 1

[defaults]
output = "human"
color = "auto"
progress = true

[[aliases]]
name = "local"
endpoint = "http://localhost:9000"
access_key = "${RUSTFS_ACCESS_KEY}"
secret_key = "${RUSTFS_SECRET_KEY}"
anonymous = false
region = "us-east-1"
signature = "v4"
bucket_lookup = "auto"
insecure = false
EOF


(
    attempts=${LEGA_INIT_ATTEMPTS:-10}
    while ! rc ready local; do
	attempts=$((attempts - 1))
        if [ "$attempts" -le 0 ]; then
            echo "Max attempts reached"
            exit 0
        fi
	sleep 1
    done
    # Ready => Create the bucket
    rc mb local/lega
    echo 'Bucket "lega" created'
) &

exec /entrypoint.sh $@
