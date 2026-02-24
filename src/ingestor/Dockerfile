FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  curl \
  ffmpeg \
  ghostscript \
  libglib2.0-0 \
  libmagic1 \
  libpoppler-cpp-dev \
  libsm6 \
  libxext6 \
  libreoffice \
  poppler-utils \
  tesseract-ocr \
  tesseract-ocr-fra \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8001

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
