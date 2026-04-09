import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gevent"
workers = 2
timeout = 3600          # Long timeout for future SSE streaming
keepalive = 75
accesslog = "-"
errorlog = "-"
loglevel = "info"
