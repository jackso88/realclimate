#!/usr/bin/env bash
set -euo pipefail

server_dir=/certs/server
client_dir=/certs/client

if [[ -f "$server_dir/kafka.keystore.p12" \
    && -f "$client_dir/kafka-ca.pem" \
    && -f "$client_dir/kafka.truststore.p12" ]]; then
    echo "Kafka TLS certificates already exist; reusing them."
    exit 0
fi

if [[ -z "${KAFKA_TLS_STORE_PASSWORD:-}" || ${#KAFKA_TLS_STORE_PASSWORD} -lt 6 ]]; then
    echo "KAFKA_TLS_STORE_PASSWORD must contain at least six characters." >&2
    exit 1
fi

rm -f "$server_dir"/* "$client_dir"/*

keytool -genkeypair \
    -noprompt \
    -alias kafka \
    -keyalg RSA \
    -keysize 3072 \
    -validity 825 \
    -storetype PKCS12 \
    -keystore "$server_dir/kafka.keystore.p12" \
    -storepass "$KAFKA_TLS_STORE_PASSWORD" \
    -keypass "$KAFKA_TLS_STORE_PASSWORD" \
    -dname "CN=kafka" \
    -ext "SAN=dns:kafka"

keytool -exportcert \
    -rfc \
    -alias kafka \
    -keystore "$server_dir/kafka.keystore.p12" \
    -storepass "$KAFKA_TLS_STORE_PASSWORD" \
    -file "$client_dir/kafka-ca.pem"

keytool -importcert \
    -noprompt \
    -alias kafka \
    -file "$client_dir/kafka-ca.pem" \
    -storetype PKCS12 \
    -keystore "$client_dir/kafka.truststore.p12" \
    -storepass "$KAFKA_TLS_STORE_PASSWORD"

chown -R 1000:1000 "$server_dir" "$client_dir"
chmod 640 "$server_dir/kafka.keystore.p12"
chmod 644 "$client_dir/kafka-ca.pem" "$client_dir/kafka.truststore.p12"
echo "Generated a private Kafka broker certificate and a client trust bundle."
