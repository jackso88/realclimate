"""Live TLS integration checks for the Compose Kafka broker.

Run in the integration-test container with:
    python -m unittest app.messaging.tests.test_messaging_kafka_tls_integration -v
"""

import os
import socket
import ssl
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(
    os.getenv("KAFKA_TLS_INTEGRATION") == "1",
    "set KAFKA_TLS_INTEGRATION=1 to run against a live Kafka broker",
)
class KafkaTLSIntegrationTests(unittest.TestCase):
    """Verify TLS trust and a Kafka message round trip against a live broker."""

    @classmethod
    def setUpClass(cls):
        """Load broker credentials and the trusted CA used by app clients."""
        from app.messaging.config import load_client_settings

        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        cls.settings = load_client_settings(bootstrap_servers)
        cls.bootstrap_server = bootstrap_servers.split(",", maxsplit=1)[0].strip()
        broker_address = cls.bootstrap_server.rsplit(":", maxsplit=1)
        if len(broker_address) != 2:
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS must contain host:port")
        cls.broker_host = broker_address[0].strip("[]")
        cls.broker_port = int(broker_address[1])

    def test_broker_presents_certificate_trusted_by_configured_ca(self):
        """Complete a TLS handshake and verify the broker certificate and cipher."""
        context = ssl.create_default_context(cafile=self.settings.ca_location)
        with socket.create_connection(
            (self.broker_host, self.broker_port), timeout=10
        ) as raw_socket:
            with context.wrap_socket(
                raw_socket, server_hostname=self.broker_host
            ) as tls_socket:
                self.assertIn(tls_socket.version(), {"TLSv1.2", "TLSv1.3"})
                self.assertIsNotNone(tls_socket.cipher())

    def test_broker_rejects_system_trust_store_without_private_ca(self):
        """Ensure the private broker certificate is not trusted by default roots."""
        context = ssl.create_default_context()
        with socket.create_connection(
            (self.broker_host, self.broker_port), timeout=10
        ) as raw_socket:
            with self.assertRaises(ssl.SSLCertVerificationError):
                context.wrap_socket(raw_socket, server_hostname=self.broker_host)

    def test_sasl_ssl_client_can_publish_and_consume_a_message(self):
        """Round-trip a unique message using the project's SASL_SSL settings."""
        from confluent_kafka import Consumer, Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        topic = f"codex.tls.integration.{uuid4().hex}"
        marker = f"tls-check-{uuid4().hex}".encode("ascii")
        client_config = self.settings.to_dict()
        admin = AdminClient(client_config)
        topic_created = False
        consumer = None
        try:
            admin.create_topics(
                [NewTopic(topic, num_partitions=1, replication_factor=1)]
            )[topic].result(timeout=30)
            topic_created = True

            producer = Producer(client_config)
            producer.produce(topic, key=b"integration-check", value=marker)
            remaining = producer.flush(15)
            self.assertEqual(remaining, 0, "Kafka did not acknowledge the test record")

            consumer = Consumer(
                {
                    **client_config,
                    "group.id": f"tls-integration-{uuid4().hex}",
                    "enable.auto.commit": False,
                    "auto.offset.reset": "earliest",
                }
            )
            consumer.subscribe([topic])
            deadline = time.monotonic() + 30
            received = None
            while time.monotonic() < deadline:
                message = consumer.poll(1)
                if message is None:
                    continue
                if message.error():
                    raise AssertionError(message.error().str())
                if message.value() == marker:
                    received = message.value()
                    break

            self.assertEqual(received, marker, "Kafka did not return the test record")
        finally:
            if consumer is not None:
                consumer.close()
            if topic_created:
                admin.delete_topics([topic])[topic].result(timeout=30)
