# Backend - Notification System

Python/FastAPI backend that receives webhooks and delivers notifications via Firebase Cloud Messaging.

## Features

- Webhook API for ingestion with API key auth
- SQLite-backed persistent queue
- Priority-aware retry logic with exponential backoff
- Background worker for FCM delivery
- Delivery acknowledgment tracking
- Dead letter queue for failed messages
- Health check endpoint for monitoring

## Prerequisites

- Python 3.10 or higher
- Firebase project with FCM enabled
- Firebase service account credentials JSON file

## Setup

### 1. Install Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Firebase Configuration

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project (or use existing)
3. Go to Project Settings → Service Accounts
4. Click "Generate New Private Key"
5. Save the JSON file as `firebase-credentials.json` in the `backend/` directory

### 3. Environment Variables

Create a `.env` file in the `backend/` directory:

```bash
# Required
API_KEY=your-webhook-api-key-here
ACK_SECRET=your-ack-secret-here
FCM_DEVICE_TOKEN=device-fcm-token-from-android-app

# Optional (defaults shown)
FCM_CREDENTIALS_PATH=./firebase-credentials.json
DATABASE_PATH=./queue.db
WORKER_POLL_INTERVAL=10
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
```

**Important**: The `FCM_DEVICE_TOKEN` must be obtained from the Android app logs after first launch (see Android README).

### 4. Generate Secure Keys

```bash
# Generate API key
python -c "import secrets; print(f'API_KEY={secrets.token_urlsafe(32)}')"

# Generate ACK secret
python -c "import secrets; print(f'ACK_SECRET={secrets.token_urlsafe(32)}')"
```

## Running the Backend

### Development Mode

```bash
cd backend
source venv/bin/activate
python -m app.main
```

The server will start on `http://localhost:8000`.

Access API docs at: `http://localhost:8000/docs`

### Production Mode

Use a production ASGI server:

```bash
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## API Endpoints

### POST /webhook
Receive notifications from external systems.

**Headers**:
- `X-API-Key: <your-api-key>`

**Body**:
```json
{
  "version": "1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Server Alert",
  "body": "CPU usage exceeded 90%",
  "priority": "critical",
  "tags": ["monitoring"],
  "source": "prometheus",
  "timestamp": "2025-12-26T10:00:00Z"
}
```

### POST /ack
Receive delivery acknowledgment from Android app.

**Headers**:
- `Authorization: Bearer <ack-secret>`

**Body**:
```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_timestamp": "2025-12-26T10:00:05Z"
}
```

### GET /health
Health check and queue statistics.

**Response**:
```json
{
  "status": "healthy",
  "queue": {
    "total": 3,
    "by_priority": {"critical": 1, "important": 2, "info": 0, "silent": 0}
  },
  "worker": {
    "alive": true
  }
}
```

## Testing

### Send Test Notification

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "version": "1.0",
    "message_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Test Notification",
    "body": "This is a test message",
    "priority": "info",
    "tags": ["test"],
    "source": "curl",
    "timestamp": "2025-12-26T10:00:00Z"
  }'
```

### Check Health

```bash
curl http://localhost:8000/health
```

## Queue Management

### View Queue Database

```bash
sqlite3 queue.db
```

```sql
-- View pending messages
SELECT message_id, priority, retry_count, last_error FROM notification_queue;

-- View dead letter messages
SELECT message_id, reason, failed_at FROM dead_letter;

-- Queue stats
SELECT priority, COUNT(*) FROM notification_queue GROUP BY priority;
```

## Troubleshooting

### Worker Not Running

Check logs for errors. Ensure Firebase credentials are valid:

```bash
python -c "import firebase_admin; from firebase_admin import credentials; cred = credentials.Certificate('firebase-credentials.json'); print('Credentials valid')"
```

### FCM Send Failures

- Verify `FCM_DEVICE_TOKEN` is correct (copy from Android app logs)
- Check Firebase project has FCM enabled
- Ensure service account has FCM permissions

### Queue Growing

- Check `/health` endpoint for worker status
- Verify Android app is receiving FCM messages (check Logcat)
- Check network connectivity to FCM API

## Deployment

### GCP Compute Engine (Free Tier)

1. Create f1-micro instance
2. Install Python 3.10+
3. Clone repo and install dependencies
4. Set environment variables
5. Run with systemd:

```bash
# /etc/systemd/system/notification-backend.service
[Unit]
Description=Notification Backend
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

### Cloud Run

Not recommended for MVP because worker runs as background thread. Use Compute Engine instead.

## Monitoring

Monitor these metrics:

- `/health` status (poll every 60s)
- Queue depth (alert if > 100)
- Dead letter count (alert if > 0)
- Worker alive status (alert if false)

## Security

- Use HTTPS in production (add reverse proxy like Caddy/nginx)
- Rotate API keys regularly
- Restrict `/webhook` endpoint to known IPs if possible
- Monitor logs for unauthorized access attempts
