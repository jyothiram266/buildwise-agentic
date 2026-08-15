# BuildWise — Public AWS EC2 Deployment & Security Guide

This guide details how to securely deploy the BuildWise Agentic AI OS on a public **AWS EC2 Instance** protected by an HTTP Basic Authentication Security Gateway.

---

## 1. Security Overview

When deploying BuildWise to a public IP address on EC2, the system must prevent unauthorized access to:
- The **Executive OS Console & Interactive Role Switcher**
- The **Governance Approval Queue** (where staff approve responses)
- The **Audit Replay Logs** (containing operational traces)
- The **Backend API Endpoints** (which consume LLM tokens)

BuildWise includes an **Nginx Security Gateway** service running on Port 80. When anyone accesses `http://<EC2-PUBLIC-IP>/`, the browser displays a native, secure login challenge asking for a **Username** and **Password** before granting access to any UI or API endpoint.

```mermaid
flowchart LR
    PublicInternet[Public Internet Client] --> SecurityGateway[Nginx Security Gateway (Port 80)]
    SecurityGateway -->|Requires Username & Password| AuthCheck{Authenticated?}
    AuthCheck -->|Yes| WebUI[Vite React UI (Port 3000)]
    AuthCheck -->|Yes| FastAPI[FastAPI Backend (Port 8000)]
    AuthCheck -->|No| Block[401 Unauthorized Block]
```

---

## 2. AWS EC2 Instance Setup

### Recommended Specifications
- **Instance Type**: `t3.medium` (2 vCPU, 4GB RAM) or higher.
- **Operating System**: Ubuntu 22.04 / 24.04 LTS.
- **Storage**: 20 GB gp3 EBS Volume.

### Security Group Inbound Rules
Configure your AWS Security Group with the following inbound rules:

| Type | Protocol | Port Range | Source | Description |
|---|---|---|---|---|
| **SSH** | TCP | 22 | `My IP` | Secure SSH administration |
| **HTTP** | TCP | 80 | `0.0.0.0/0` | Public Web OS protected by Basic Auth |
| **HTTPS** *(Optional)* | TCP | 443 | `0.0.0.0/0` | SSL/TLS encrypted traffic |

> **Note**: You do **not** need to open ports 3000, 8000, 5432, or 6379 to the internet. Nginx routes internal traffic securely between containers.

---

## 3. Step-by-Step Deployment Commands

### Step 1: Connect to your EC2 Instance
```bash
ssh -i /path/to/your-key.pem ubuntu@<YOUR-EC2-PUBLIC-IP>
```

### Step 2: Install Docker & Docker Compose
```bash
# Update package index and install prerequisites
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git

# Enable and start Docker service
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu

# Refresh shell group permissions
newgrp docker
```

### Step 3: Clone the Repository
```bash
git clone https://github.com/YESVIN2807/buildwise-agentic.git
cd buildwise-agentic
```

### Step 4: Configure Credentials in `.env`
Copy the environment template:
```bash
cp .env.example .env
```

Edit `.env` using `nano .env` or `vim .env` and set your desired **Username**, **Password**, and **OpenAI API Key**:

```ini
# --- Auth & Security Gateway (Public EC2 Protection) ---
SECURITY_USER=admin
SECURITY_PASSWORD=YourStrongSecretPassword123!

# --- Language Model ---
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-your-actual-openai-key-here
```

### Step 5: Start the Container Stack
Run Docker Compose in detached mode:
```bash
docker compose up -d --build
```

This starts 6 orchestrated containers:
1. `buildwise-proxy-1`: Nginx Security Gateway (Port 80)
2. `buildwise-web-1`: React + Vite Glassmorphic Frontend (Port 3000)
3. `buildwise-api-1`: FastAPI Core Backend (Port 8000)
4. `buildwise-postgres-1`: PostgreSQL 16 + pgvector (Port 5432)
5. `buildwise-redis-1`: Redis Cache (Port 6379)
6. `buildwise-mock-connectors-1`: Systems of Record Mock Server (Port 8100)

### Step 6: Bootstrap Database & Knowledge Base
Run database migrations and ingest the initial knowledge base corpus:
```bash
docker compose exec api python -m db.seed
docker compose exec api python -m retrieval.ingest
```

---

## 4. Accessing the Application

1. Open your browser and navigate to:
   ```text
   http://<YOUR-EC2-PUBLIC-IP>/
   ```
2. The browser will prompt for credentials:
   - **Username**: `admin` (or the value set in `SECURITY_USER`)
   - **Password**: `YourStrongSecretPassword123!` (or the value set in `SECURITY_PASSWORD`)
3. After logging in, you have full secure access to the BuildWise Glassmorphic AI OS Console!

---

## 5. Changing Credentials or Restarting

To change your login username or password at any time:
1. Edit `.env`:
   ```bash
   nano .env
   ```
2. Restart the `proxy` service:
   ```bash
   docker compose restart proxy
   ```

To stop or restart the entire stack:
```bash
# Stop all services
docker compose down

# Start all services
docker compose up -d
```
