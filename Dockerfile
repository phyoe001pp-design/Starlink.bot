FROM python:3.10-slim

# System dependencies အတွက် လိုအပ်သော Linux packages များ သွင်းခြင်း
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Web Server အတွက် Port ဖွင့်ပေးခြင်း
EXPOSE 8080

CMD ["python", "main.py"]
