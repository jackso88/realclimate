#!/usr/bin/env bash
set -euo pipefail

kafka_bin=/opt/kafka/bin
data_dir=/var/lib/kafka/data
config_file=/tmp/kafka-server.properties
keystore=/run/secrets/kafka-server/kafka.keystore.p12

require_safe_value() {
    local name="$1"
    local value="$2"
    if [[ -z "$value" || ! "$value" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        echo "$name must be non-empty and contain only letters, digits, dot, underscore, or dash." >&2
        exit 1
    fi
}

require_safe_value KAFKA_SASL_USERNAME "${KAFKA_SASL_USERNAME:-}"
require_safe_value KAFKA_SASL_PASSWORD "${KAFKA_SASL_PASSWORD:-}"
require_safe_value KAFKA_TLS_STORE_PASSWORD "${KAFKA_TLS_STORE_PASSWORD:-}"

cat >"$config_file" <<EOF
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@kafka:9093
listeners=SASL_SSL://:9092,CONTROLLER://:9093,ADMIN://127.0.0.1:9094
advertised.listeners=SASL_SSL://kafka:9092,ADMIN://127.0.0.1:9094
listener.security.protocol.map=SASL_SSL:SASL_SSL,CONTROLLER:PLAINTEXT,ADMIN:PLAINTEXT
inter.broker.listener.name=SASL_SSL
controller.listener.names=CONTROLLER
log.dirs=$data_dir
num.partitions=3
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
log.retention.hours=1
message.max.bytes=80000000
socket.request.max.bytes=80000000
replica.fetch.max.bytes=80000000
auto.create.topics.enable=false
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="$KAFKA_SASL_USERNAME" password="$KAFKA_SASL_PASSWORD";
listener.name.sasl_ssl.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required;
ssl.keystore.location=$keystore
ssl.keystore.password=$KAFKA_TLS_STORE_PASSWORD
ssl.key.password=$KAFKA_TLS_STORE_PASSWORD
ssl.keystore.type=PKCS12
ssl.truststore.location=/run/secrets/kafka-client/kafka.truststore.p12
ssl.truststore.password=$KAFKA_TLS_STORE_PASSWORD
ssl.truststore.type=PKCS12
ssl.client.auth=none
EOF
chmod 600 "$config_file"

if [[ ! -f "$data_dir/meta.properties" ]]; then
    cluster_id=$("$kafka_bin/kafka-storage.sh" random-uuid)
    "$kafka_bin/kafka-storage.sh" format \
        --cluster-id "$cluster_id" \
        --config "$config_file"
fi

echo "Starting the Kafka broker."
"$kafka_bin/kafka-server-start.sh" "$config_file" &
broker_pid=$!
trap 'kill "$broker_pid" 2>/dev/null || true; wait "$broker_pid" 2>/dev/null || true' TERM INT

ready=false
probe_output=/tmp/kafka-bootstrap-probe.log
for _ in $(seq 1 90); do
    if ! kill -0 "$broker_pid" 2>/dev/null; then
        wait "$broker_pid"
    fi
    if "$kafka_bin/kafka-broker-api-versions.sh" \
        --bootstrap-server localhost:9094 >"$probe_output" 2>&1; then
        ready=true
        break
    fi
    sleep 2
done

if [[ "$ready" != true ]]; then
    echo "Kafka did not become ready on its local bootstrap listener." >&2
    cat "$probe_output" >&2 || true
    exit 1
fi

# The loopback-only listener permits first-boot SCRAM setup and migration from
# the previous plaintext volume without exposing an unauthenticated network port.
echo "Kafka broker is ready; provisioning the SCRAM user."
"$kafka_bin/kafka-configs.sh" \
    --bootstrap-server localhost:9094 \
    --alter \
    --entity-type users \
    --entity-name "$KAFKA_SASL_USERNAME" \
    --add-config "SCRAM-SHA-512=[iterations=8192,password=$KAFKA_SASL_PASSWORD]"

echo "Kafka SCRAM user provisioned; broker is healthy."
touch /tmp/kafka-ready
wait "$broker_pid"
