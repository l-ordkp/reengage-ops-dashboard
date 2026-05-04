# Stage 1: Build Next.js frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=983150008719-7v42pvpog93epoaf8fs8jlrmmv4f7ss0.apps.googleusercontent.com
ENV NEXT_PUBLIC_OAUTH_REDIRECT_URI=https://reengage-ops-dashboard-v2-ul5ne76yva-uc.a.run.app/login
RUN npm run build

# Stage 2: Runtime
FROM python:3.10-slim
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc nginx curl nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy legacy files still needed (extension_api, cron, etc.)
COPY config.py assignment.py auth.py data_loaders.py db.py pg_db.py \
     write_helpers.py response_generator.py secret_manager.py models.py \
     extension_api.py cron_assignment.py ./

# Copy Next.js standalone build
COPY --from=frontend-builder /app/frontend/.next/standalone ./frontend/
COPY --from=frontend-builder /app/frontend/.next/static ./frontend/.next/static
COPY --from=frontend-builder /app/frontend/public ./frontend/public

# nginx config
COPY nginx.conf /etc/nginx/nginx.conf

ENV PORT=8080
EXPOSE ${PORT}

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
