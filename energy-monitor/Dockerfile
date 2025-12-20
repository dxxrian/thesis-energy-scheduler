FROM python:3.9-slim
WORKDIR /app
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/energy_monitor.py .
CMD ["python", "-u", "energy_monitor.py"]
