FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Utilisateur non-root
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'app
COPY . .

USER app
EXPOSE 8501
# Commande par défaut (le compose mappe déjà 8501 -> ${NGINX_UI_PORT})
CMD ["streamlit","run","app.py","--server.port","8501","--server.address","0.0.0.0"]
