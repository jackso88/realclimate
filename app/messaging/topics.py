"""Kafka topic names used by the application services."""

REFERENCE_SYNC_REQUESTS = "reference.sync.requests"
REFERENCE_DOWNLOADS = "downloader.reference.completed"
REFERENCE_PIPELINE_COMPLETED = "reference.pipeline.completed"
REFERENCE_SNAPSHOT_STATE = "reference.snapshot.state"
CURRENT_DOWNLOADS = "downloader.current.completed"
CORE_PROCESS_RESULTS = "core.process.results"
CORE_DUPLICATE_MAP_STATE = "core.duplicate-map.state"
# Absent-article state now lives in PostgreSQL. This name is only read once, to
# import the state left by earlier versions; the topic is no longer created.
LEGACY_ABSENT_ARTICLES_STATE = "core.absent-articles.state"
ADMIN_AUTH_REQUESTS = "admin-auth.requests"
ADMIN_AUTH_CURRENT_RESPONSES = "admin-auth.current.responses"
ADMIN_AUTH_UPLOADER_RESPONSES = "admin-auth.uploader.responses"
CORE_NOTIFICATIONS = "notifications"
HEALTH_HEARTBEATS = "health.heartbeats"
RATE_LIMIT_REQUESTS = "rate.limit.requests"
RATE_LIMIT_RESPONSES = "rate.limit.responses"
