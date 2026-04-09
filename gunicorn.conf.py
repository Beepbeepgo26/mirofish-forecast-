import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
workers = 1       # Single process — required for in-memory session dict
threads = 8       # Concurrency via threads instead of processes
timeout = 3600          # Long timeout for future SSE streaming
keepalive = 75
accesslog = "-"
errorlog = "-"
loglevel = "info"
