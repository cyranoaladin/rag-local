FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Utilisateur non-root
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'API
COPY . .

USER app
EXPOSE 8001
# Le compose surchargera éventuellement la commande, mais on met un défaut correct :
CMD ["uvicorn","api:app","--host","0.0.0.0","--port","8001"]
