ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

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
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

ARG MULTIMODAL_DEPS=0
RUN if [ "$MULTIMODAL_DEPS" = "1" ]; then \
      python -m pip install --no-cache-dir raganything Pillow; \
    else \
      echo "Skipping multimodal dependencies"; \
    fi

COPY . ./

EXPOSE 8001

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
