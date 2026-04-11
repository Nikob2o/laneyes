FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends nmap iproute2 iputils-ping && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "run.py"]
