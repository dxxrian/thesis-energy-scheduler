FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY energy_monitor.py .
CMD ["python", "-u", "energy_monitor.py"]
