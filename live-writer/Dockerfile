FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY writer.py .

# Cloud Run requires a container that serves HTTP on $PORT.
# The writer spawns a tiny health thread on that port while the
# main thread runs the blocking Databento Live connection.
EXPOSE 8080

CMD ["python", "-u", "writer.py"]
