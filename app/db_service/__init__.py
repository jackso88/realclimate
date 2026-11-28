"""Database service: the only component that talks to PostgreSQL.

Other services send commands over Kafka (``db.requests``) and receive the
answers on ``db.responses``; none of them opens a database connection.
"""
