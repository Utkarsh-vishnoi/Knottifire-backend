# HTTPS Deployment Guide for GCP e2-micro

This guide walks you through setting up HTTPS with Let's Encrypt auto-renewal for the Knottifire backend on a GCP e2-micro instance.

## Prerequisites

- GCP e2-micro instance running Ubuntu/Debian
- Domain name: `notification.utkarsh.cloudns.asia` pointing to your instance's public IP
- SSH access to your instance
- Ports 80 and 443 open in GCP firewall

## Step 1: Verify DNS Configuration

Before starting, ensure your domain points to your GCP instance:

```bash
# From your local machine
nslookup notification.utkarsh.cloudns.asia

# Or
dig notification.utkarsh.cloudns.asia
```

The IP should match your GCP instance's external IP.

## Step 2: Configure GCP Firewall Rules

Ensure HTTP (80) and HTTPS (443) are open:

```bash
# From GCP Console or using gcloud CLI
gcloud compute firewall-rules create allow-http \
    --allow tcp:80 \
    --description "Allow HTTP traffic" \
    --direction INGRESS

gcloud compute firewall-rules create allow-https \
    --allow tcp:443 \
    --description "Allow HTTPS traffic" \
    --direction INGRESS
```

## Step 3: SSH into Your GCP Instance

```bash
gcloud compute ssh your-instance-name --zone your-zone
```

## Step 4: Install System Dependencies

```bash
# Update system packages
sudo apt update
sudo apt upgrade -y

# Install Python, pip, and required system packages
sudo apt install -y python3 python3-pip python3-venv git

# Install Caddy (automatic HTTPS with Let's Encrypt)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

## Step 5: Deploy Application

```bash
# Create deployment directory
sudo mkdir -p /opt/knottifire
sudo chown $USER:$USER /opt/knottifire

# Clone or copy your application
cd /opt/knottifire
# If using git:
# git clone <your-repo-url> .
# Or copy files manually using scp

# For now, copy files from your local machine:
# From your local machine (in a new terminal):
# scp -r /path/to/Knottifire-backend/* your-instance-ip:/opt/knottifire/
```

## Step 6: Set Up Python Virtual Environment

```bash
cd /opt/knottifire

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn  # Production WSGI server
```

## Step 7: Configure Environment Variables

Create the `.env` file with your production settings:

```bash
sudo nano /opt/knottifire/.env
```

Add the following (customize with your actual values):

```bash
# API Authentication
API_KEY=your-production-webhook-api-key-change-this
ACK_SECRET=your-production-ack-secret-change-this

# Firebase Configuration
FCM_CREDENTIALS_PATH=/opt/knottifire/firebase-credentials.json
FCM_DEVICE_TOKEN=your-actual-device-token

# Database
DATABASE_PATH=/opt/knottifire/queue.db

# Worker Configuration
WORKER_POLL_INTERVAL=10
LOG_LEVEL=INFO

# Server Configuration (bound to localhost since Caddy will proxy)
HOST=127.0.0.1
PORT=8000
```

Save and exit (Ctrl+X, Y, Enter).

## Step 8: Upload Firebase Credentials

Copy your Firebase credentials to the server:

```bash
# From your local machine (in a new terminal):
scp /path/to/firebase-credentials.json your-instance-ip:/opt/knottifire/firebase-credentials.json
```

Then on the server, set proper permissions:

```bash
sudo chown www-data:www-data /opt/knottifire/firebase-credentials.json
sudo chmod 600 /opt/knottifire/firebase-credentials.json
```

## Step 9: Set Up Application as Systemd Service

```bash
# Copy the service file to systemd directory
sudo cp /opt/knottifire/knottifire.service /etc/systemd/system/

# Set proper ownership for application files
sudo chown -R www-data:www-data /opt/knottifire

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable knottifire

# Start the service
sudo systemctl start knottifire

# Check status
sudo systemctl status knottifire
```

You should see the service running. Check logs if there are any errors:

```bash
# View logs
sudo journalctl -u knottifire -f
```

## Step 10: Configure Caddy for HTTPS

```bash
# Copy the Caddyfile to Caddy's configuration directory
sudo cp /opt/knottifire/Caddyfile /etc/caddy/Caddyfile

# Create log directory
sudo mkdir -p /var/log/caddy
sudo chown caddy:caddy /var/log/caddy

# Test Caddy configuration
sudo caddy validate --config /etc/caddy/Caddyfile

# Reload Caddy (this will automatically obtain Let's Encrypt certificate)
sudo systemctl reload caddy

# Check Caddy status
sudo systemctl status caddy
```

## Step 11: Verify HTTPS is Working

Caddy will automatically:
1. Request a Let's Encrypt certificate for `notification.utkarsh.cloudns.asia`
2. Configure HTTPS with the certificate
3. Redirect HTTP to HTTPS
4. Auto-renew certificates before expiry

Test your endpoints:

```bash
# From your local machine or browser
curl https://notification.utkarsh.cloudns.asia/

# Check health endpoint
curl https://notification.utkarsh.cloudns.asia/health

# Test webhook (replace with your API key)
curl -X POST https://notification.utkarsh.cloudns.asia/webhook/native \
  -H "X-API-Key: your-production-webhook-api-key-change-this" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Notification",
    "body": "HTTPS is working!",
    "priority": "info"
  }'
```

## Step 12: Monitor Certificate Auto-Renewal

Caddy automatically renews certificates. You can verify this:

```bash
# Check certificate details
curl -vI https://notification.utkarsh.cloudns.asia 2>&1 | grep -A 10 "Server certificate"

# View Caddy logs for renewal information
sudo journalctl -u caddy -f

# Caddy stores certificates in:
ls -la /var/lib/caddy/.local/share/caddy/certificates/
```

Caddy will automatically renew certificates 30 days before expiry.

## Maintenance Commands

### Application Service

```bash
# Start/Stop/Restart the application
sudo systemctl start knottifire
sudo systemctl stop knottifire
sudo systemctl restart knottifire

# View application logs
sudo journalctl -u knottifire -f

# Check application status
sudo systemctl status knottifire
```

### Caddy Service

```bash
# Reload Caddy configuration (zero downtime)
sudo systemctl reload caddy

# Restart Caddy
sudo systemctl restart caddy

# View Caddy logs
sudo journalctl -u caddy -f

# Check Caddy status
sudo systemctl status caddy
```

### Update Application Code

```bash
# Stop the service
sudo systemctl stop knottifire

# Update code (git pull or copy new files)
cd /opt/knottifire
# git pull  # if using git

# Activate virtual environment and update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Ensure proper ownership
sudo chown -R www-data:www-data /opt/knottifire

# Start the service
sudo systemctl start knottifire

# Check status
sudo systemctl status knottifire
```

## Security Best Practices

1. **Use strong API keys**: Generate secure random strings for `API_KEY` and `ACK_SECRET`
   ```bash
   # Generate secure random keys
   openssl rand -hex 32
   ```

2. **Restrict file permissions**:
   ```bash
   sudo chmod 600 /opt/knottifire/.env
   sudo chmod 600 /opt/knottifire/firebase-credentials.json
   ```

3. **Enable firewall** (UFW):
   ```bash
   sudo ufw allow 22/tcp   # SSH
   sudo ufw allow 80/tcp   # HTTP (for Let's Encrypt)
   sudo ufw allow 443/tcp  # HTTPS
   sudo ufw enable
   ```

4. **Regular updates**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

5. **Monitor logs** regularly for suspicious activity

## Troubleshooting

### Certificate Not Obtained

If Let's Encrypt certificate fails:

1. Verify DNS is correctly pointing to your instance
2. Ensure ports 80 and 443 are accessible
3. Check Caddy logs: `sudo journalctl -u caddy -n 100`
4. Verify domain in browser shows Caddy's default page (before configuring reverse proxy)

### Application Not Responding

1. Check application status: `sudo systemctl status knottifire`
2. View logs: `sudo journalctl -u knottifire -n 100`
3. Verify environment variables in `/opt/knottifire/.env`
4. Check if application is listening: `sudo netstat -tlnp | grep 8000`

### 502 Bad Gateway

1. Verify application is running: `sudo systemctl status knottifire`
2. Check if app is listening on 127.0.0.1:8000: `curl http://127.0.0.1:8000/health`
3. Review Caddy configuration: `sudo caddy validate --config /etc/caddy/Caddyfile`

### Database Permissions

If you see database permission errors:

```bash
sudo chown www-data:www-data /opt/knottifire/queue.db
sudo chmod 644 /opt/knottifire/queue.db
```

## Monitoring

Set up monitoring for:

1. **Application health**: Use `/health` endpoint
2. **SSL certificate expiry**: Caddy handles this automatically, but you can monitor via:
   ```bash
   echo | openssl s_client -servername notification.utkarsh.cloudns.asia -connect notification.utkarsh.cloudns.asia:443 2>/dev/null | openssl x509 -noout -dates
   ```
3. **System resources**: Monitor CPU, memory, disk on GCP console
4. **Application logs**: `sudo journalctl -u knottifire -f`

## Summary

Your application is now:
- ✅ Running with HTTPS on `https://notification.utkarsh.cloudns.asia`
- ✅ Using Let's Encrypt certificates (auto-renewed by Caddy)
- ✅ Configured as a systemd service (auto-starts on boot)
- ✅ Protected with security headers
- ✅ Logging access and errors
- ✅ Production-ready with Gunicorn + Uvicorn workers

**Certificate Renewal**: Fully automatic - Caddy renews certificates 30 days before expiry with zero downtime.

**Email Notifications**: You'll receive emails at `utkarshvishnoi25@gmail.com` for any certificate-related issues.
