FROM --platform=linux/x86_64 python:3.11-slim

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:bot_app", "--host", "0.0.0.0", "--port", "8000"]