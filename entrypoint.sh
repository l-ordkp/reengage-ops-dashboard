#!/bin/bash
# Start FastAPI backend + Next.js frontend behind nginx

# Start FastAPI (all API routes including extension)
cd /app && uvicorn backend.main:app --host 0.0.0.0 --port 8001 &
FASTAPI_PID=$!

# Start Next.js standalone server
cd /app/frontend && PORT=3000 node server.js &
NEXT_PID=$!

# Wait for both to be ready
for i in $(seq 1 60); do
    FASTAPI_OK=false
    NEXT_OK=false
    curl -sf http://localhost:8001/api/health > /dev/null 2>&1 && FASTAPI_OK=true
    curl -sf http://localhost:3000 > /dev/null 2>&1 && NEXT_OK=true
    if $FASTAPI_OK && $NEXT_OK; then
        echo "All services ready"
        break
    fi
    sleep 1
done

# Start nginx in foreground
nginx -g 'daemon off;' &
NGINX_PID=$!

# If Next.js dies, exit so Cloud Run restarts the container
wait $NEXT_PID
kill $FASTAPI_PID 2>/dev/null
kill $NGINX_PID 2>/dev/null
exit 1
