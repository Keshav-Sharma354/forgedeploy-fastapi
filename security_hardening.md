# Production VPS Operating System Security Hardening Guide

Deploying a production API to a Linux Virtual Private Server (VPS) requires implementing active protection at the operating system, networking, and containerization layers. This document details the setup steps, configurations, and rationales for securing your production server.

---

## 1. SSH Hardening (Secure Remote Administration)

Standard VPS setups often allow password-based root login. This is highly vulnerable to brute-force attacks.

### Hardening Steps:
1. **Disable Password Authentication**: Force the use of secure SSH Key-pairs only.
2. **Disable Root SSH Access**: Force operators to log in as a restricted deploy user and use `sudo` for administrative privileges.
3. **Change Default SSH Port**: Move the SSH listening port from `22` to a non-standard port (e.g., `22022`) to filter out 99% of automated scanner scripts.

### Implementation:
Edit the SSH daemon configuration file on the VPS:
```bash
sudo nano /etc/ssh/sshd_config
```

Ensure the following parameters match these hardened directives:
```ini
Port 22022
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
PermitEmptyPasswords no
X11Forwarding no
MaxAuthTries 3
```

Restart the SSH daemon to apply:
```bash
sudo systemctl restart sshd
```

> [!CAUTION]
> Ensure you have successfully copied your public SSH key to the remote server before restarting the daemon, otherwise you will lock yourself out!

---

## 2. Firewall Protection (UFW - Uncomplicated Firewall)

A robust firewall must implement the **Principle of Least Privilege**, closing all communication ports except those explicitly required for standard operation (HTTP, HTTPS, and SSH).

### Configuration Commands:
```bash
# 1. Set default policies to block all incoming and allow all outgoing traffic
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 2. Allow your custom hardened SSH port
sudo ufw allow 22022/tcp comment 'Hardened SSH Access'

# 3. Allow standard web traffic
sudo ufw allow 80/tcp comment 'HTTP Web Verification'
sudo ufw allow 443/tcp comment 'HTTPS Production Traffic'

# 4. Enable the firewall
sudo ufw enable
```

### Verification:
```bash
sudo ufw status verbose
```

* **Why it matters**: Restricting open ports prevents attackers from identifying and exploiting unauthorized databases (like exposing Postgres or Redis) or system debugging services that may be running on the host.

---

## 3. Brute-Force Defense (Fail2Ban Setup)

Fail2Ban monitors log files (e.g., `/var/log/auth.log`) for failed authentication attempts and dynamically adds temporary IP bans using system firewall rules.

### Installation & Configuration:
Install Fail2Ban:
```bash
sudo apt-get update && sudo apt-get install -y fail2ban
```

Create a custom jail configuration overrides file:
```bash
sudo nano /etc/fail2ban/jail.local
```

Add the following configurations:
```ini
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled  = true
port     = 22022
logpath  = %(sshd_log)s
backend  = %(sshd_backend)s
maxretry = 3
```

Start and enable the service:
```bash
sudo systemctl start fail2ban
sudo systemctl enable fail2ban
```

Check active protection status:
```bash
sudo fail2ban-client status sshd
```

* **Why it matters**: Brute-force botnets scan millions of IPs daily. Fail2Ban detects these automated scans and drops their traffic instantly, reducing system resource utilization and blocking credential harvesting.

---

## 4. Non-Root Deploy User

Running deployments and commands as the `root` administrative user is highly dangerous. A dedicated `deployuser` with limited access should be created.

### Setup Steps:
```bash
# 1. Create a dedicated deploy system user
sudo adduser deployuser

# 2. Add the user to the sudo administrative group
sudo usermod -aG sudo deployuser

# 3. Add the user to the docker group (to execute docker compose without sudo)
sudo usermod -aG docker deployuser

# 4. Configure authorized SSH keys for the deploy user
sudo mkdir -p /home/deployuser/.ssh
sudo cp /root/.ssh/authorized_keys /home/deployuser/.ssh/
sudo chown -R deployuser:deployuser /home/deployuser/.ssh
sudo chmod 700 /home/deployuser/.ssh
sudo chmod 600 /home/deployuser/.ssh/authorized_keys
```

* **Why it matters**: If a deployment script contains bugs or is hijacked, the scope of damage is strictly limited to the `deployuser` privileges, protecting system configuration kernels.

---

## 5. Docker Infrastructure Hardening

Docker runs with root-level privileges by default. We must apply custom sandboxing to protect host resources.

### Hardening Actions:

#### A. Running FastAPI as Non-Root User
Our `Dockerfile` implements a custom non-root system user context:
```dockerfile
RUN groupadd -g 10001 webgroup && \
    useradd -r -u 10001 -g webgroup webuser
USER webuser
```
* **Why it matters**: If an attacker exploits a remote code execution vulnerability in FastAPI, the non-root constraints prevent them from editing system files inside the container or attempting a container escape to take control of the VPS.

#### B. Network Isolation
Our `docker-compose.yml` implements two separate virtual bridge networks:
1. `frontend-net`: Links NGINX and FastAPI.
2. `backend-net`: Links FastAPI, PostgreSQL, and Redis.
* **Why it matters**: Under this design, the database and caching services do not belong to the frontend network. If NGINX is compromised, the attacker has **NO** direct network access to the database or caching engines, adding a robust layer of defense-in-depth.

#### C. Docker Log Rotation
Uncontrolled container log growth can exhaust VPS disk space, causing databases to crash. Configure log-limits inside the Docker daemon global configurations:
Create or edit `/etc/docker/daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```
Restart Docker daemon to apply:
```bash
sudo systemctl restart docker
```
* **Why it matters**: Limits total logging utilization to a maximum of 30MB per container, preserving disk limits.
