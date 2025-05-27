FROM python:3.13.3-slim

# Install WeasyPrint dependencies first to cache this layer
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libffi-dev \
    build-essential \
    libpq-dev \
    curl \
    && pip install weasyprint flask google-api-python-client google-auth google-auth-oauthlib python-dateutil requests \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set workdir and copy code
WORKDIR /app
COPY . /app

EXPOSE 8080
CMD ["python", "app.py"]
