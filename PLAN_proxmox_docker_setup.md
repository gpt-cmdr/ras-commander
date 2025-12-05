# Proxmox Docker Worker Setup Plan

**Goal:** Set up Docker containers on 3 Proxmox servers to run HEC-RAS for distributed execution testing

**Servers:**
| Name | IP | Proxmox Port | Resources (Estimated) |
|------|----|--------------|-----------------------|
| MediaQuad | 192.168.3.2 | 8006 | TBD - need to query |
| CLB-02 | 192.168.3.6 | 8006 | TBD - need to query |
| CLB-03 | 192.168.3.20 | 8006 | TBD - need to query |

**Credentials:** root / MattCLB11!!

---

## Architecture Decision

### Option A: LXC Containers (Recommended)
- Lightweight, fast startup
- Direct Docker installation in privileged container
- Best performance for HEC-RAS workloads
- ~512MB-1GB overhead per container

### Option B: Full VMs
- More isolated but heavier
- Better for production environments
- ~2-4GB overhead per VM

**Recommendation:** Use **privileged LXC containers** for testing - lighter weight and faster to deploy.

---

## Phase 1: Gather Server Information (First)

Before provisioning, we need to know what resources each Proxmox server has:

**Tasks per server:**
1. SSH into server: `ssh root@{IP}`
2. Query total CPU cores: `nproc` or `lscpu`
3. Query total RAM: `free -h`
4. Query available storage: `pvesm status`
5. List existing VMs/containers: `pct list && qm list`

**This information will determine:**
- How many cores to allocate (50% of total)
- How much memory to allocate (50% of total)
- Which storage pool to use

---

## Phase 2: Create Docker LXC Containers (Per Server)

### Step 2.1: Download Container Template

```bash
# SSH into Proxmox
ssh root@192.168.3.2

# Download Rocky Linux 8 template (matches HEC-RAS target)
pveam update
pveam download local rockylinux-8-default_20221212_amd64.tar.xz
```

### Step 2.2: Create Privileged LXC Container

```bash
# Create container (adjust VMID, storage, and resources per server)
pct create 200 local:vztmpl/rockylinux-8-default_20221212_amd64.tar.xz \
    --hostname docker-hecras \
    --memory {50% of host RAM in MB} \
    --cores {all host cores} \
    --net0 name=eth0,bridge=vmbr0,ip=dhcp \
    --storage local-lvm \
    --rootfs local-lvm:32 \
    --features nesting=1 \
    --unprivileged 0 \
    --password MattCLB11!!
```

**Container IDs:**
- MediaQuad (192.168.3.2): VMID 200
- CLB-02 (192.168.3.6): VMID 200
- CLB-03 (192.168.3.20): VMID 200

### Step 2.3: Configure Container for Docker

After creating, edit container config to enable required features:

```bash
# Edit config
nano /etc/pve/lxc/200.conf

# Add these lines for Docker support:
lxc.apparmor.profile: unconfined
lxc.cgroup2.devices.allow: a
lxc.cap.drop:
lxc.mount.auto: proc:rw sys:rw
```

### Step 2.4: Start Container and Install Docker

```bash
# Start container
pct start 200

# Enter container
pct enter 200

# Inside container - install Docker
dnf -y install dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin
systemctl enable --now docker

# Verify Docker works
docker info
```

---

## Phase 3: Build HEC-RAS Docker Images

### Step 3.1: Download HEC-RAS Linux Binaries

Inside each container, download HEC-RAS Linux versions:

```bash
# Create build directory
mkdir -p /opt/hecras-builds
cd /opt/hecras-builds

# Download all versions
wget https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip
wget https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip
wget https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip
wget https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip

# Extract
unzip Linux_RAS_v66.zip
unzip Linux_RAS_v65.zip
unzip HEC-RAS_610_Linux.zip
unzip HEC-RAS_507_linux.zip
```

### Step 3.2: Create Dockerfiles

**Dockerfile.6.6:**
```dockerfile
FROM rockylinux:8

# Install runtime dependencies
RUN dnf -y install libgfortran wget unzip && dnf clean all

# Copy HEC-RAS binaries
COPY Linux_RAS_v66/RAS_v66/Release/ /app/bin/
COPY Linux_RAS_v66/libs/ /app/libs/

# Set library path and permissions
ENV LD_LIBRARY_PATH=/app/libs
RUN chmod +x /app/bin/*

# Create workspace
WORKDIR /workspace

ENTRYPOINT ["/app/bin/RasUnsteady"]
```

**Dockerfile.6.5:**
```dockerfile
FROM rockylinux:8
RUN dnf -y install libgfortran wget unzip && dnf clean all
COPY Linux_RAS_v65/RAS_v65/Release/ /app/bin/
COPY Linux_RAS_v65/libs/ /app/libs/
ENV LD_LIBRARY_PATH=/app/libs
RUN chmod +x /app/bin/*
WORKDIR /workspace
ENTRYPOINT ["/app/bin/RasUnsteady"]
```

**Dockerfile.6.1:**
```dockerfile
FROM rockylinux:8
RUN dnf -y install libgfortran wget unzip && dnf clean all
# Note: 6.1 has nested zip structure
COPY HEC-RAS_610_Linux/Ras_v61/Release/ /app/bin/
COPY HEC-RAS_610_Linux/libs/ /app/libs/
ENV LD_LIBRARY_PATH=/app/libs
RUN chmod +x /app/bin/*
WORKDIR /workspace
ENTRYPOINT ["/app/bin/RasUnsteady"]
```

**Dockerfile.5.0.7:**
```dockerfile
FROM centos:7
RUN yum -y install libgfortran wget unzip && yum clean all
# Note: 5.0.7 has different structure - bins and libs in same folder
COPY RAS_507_linux/bin_ras/ /app/bin/
ENV LD_LIBRARY_PATH=/app/bin
RUN chmod +x /app/bin/*
WORKDIR /workspace
# Note: 5.0.7 uses rasUnsteady64 (different name)
ENTRYPOINT ["/app/bin/rasUnsteady64"]
```

### Step 3.3: Build All Images

```bash
cd /opt/hecras-builds

docker build -f Dockerfile.6.6 -t hecras:6.6 .
docker build -f Dockerfile.6.5 -t hecras:6.5 .
docker build -f Dockerfile.6.1 -t hecras:6.1 .
docker build -f Dockerfile.5.0.7 -t hecras:5.0.7 .

# Verify all images
docker images | grep hecras
```

**Expected disk usage:** ~10-12 GB per container for all 4 images

---

## Phase 4: Configure SSH Access

### Step 4.1: Set Up SSH Server in Container

```bash
# Inside container
dnf -y install openssh-server
systemctl enable --now sshd

# Create SSH key for root
mkdir -p /root/.ssh
chmod 700 /root/.ssh
```

### Step 4.2: Copy SSH Key from Windows Control Machine

From your Windows machine:

```powershell
# Generate key if you don't have one
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\docker_worker

# Copy key to each container (you'll need container IPs)
type $env:USERPROFILE\.ssh\docker_worker.pub | ssh root@{CONTAINER_IP} "cat >> /root/.ssh/authorized_keys"

# Test connection
ssh -i $env:USERPROFILE\.ssh\docker_worker root@{CONTAINER_IP} "docker info"
```

---

## Phase 5: Configure Samba Share (File Transfer)

### Step 5.1: Install and Configure Samba

```bash
# Inside container
dnf -y install samba samba-client

# Create share directory
mkdir -p /mnt/RasRemote
chmod 777 /mnt/RasRemote

# Configure Samba
cat >> /etc/samba/smb.conf << 'EOF'
[RasRemote]
    path = /mnt/RasRemote
    browseable = yes
    read only = no
    guest ok = yes
    create mask = 0777
    directory mask = 0777
    force user = root
EOF

# Start Samba
systemctl enable --now smb nmb

# Allow through firewall
firewall-cmd --permanent --add-service=samba
firewall-cmd --reload
```

### Step 5.2: Test Share from Windows

```cmd
dir \\{CONTAINER_IP}\RasRemote
```

---

## Phase 6: Update RemoteWorkers.json

After all containers are set up, get their IP addresses and update the config:

```json
{
  "workers": [
    {
      "name": "MediaQuad Docker 6.6",
      "worker_type": "docker",
      "docker_image": "hecras:6.6",
      "docker_host": "ssh://root@{MEDIAQUAD_CONTAINER_IP}",
      "share_path": "\\\\{MEDIAQUAD_CONTAINER_IP}\\RasRemote",
      "remote_staging_path": "/mnt/RasRemote",
      "use_ssh_client": true,
      "cores_total": 8,
      "cores_per_plan": 4,
      "preprocess_on_host": true,
      "max_runtime_minutes": 60,
      "queue_priority": 1,
      "enabled": true
    },
    {
      "name": "CLB-02 Docker 6.6",
      "worker_type": "docker",
      "docker_image": "hecras:6.6",
      "docker_host": "ssh://root@{CLB02_CONTAINER_IP}",
      "share_path": "\\\\{CLB02_CONTAINER_IP}\\RasRemote",
      "remote_staging_path": "/mnt/RasRemote",
      "use_ssh_client": true,
      "cores_total": 8,
      "cores_per_plan": 4,
      "preprocess_on_host": true,
      "max_runtime_minutes": 60,
      "queue_priority": 2,
      "enabled": true
    },
    {
      "name": "CLB-03 Docker 6.6",
      "worker_type": "docker",
      "docker_image": "hecras:6.6",
      "docker_host": "ssh://root@{CLB03_CONTAINER_IP}",
      "share_path": "\\\\{CLB03_CONTAINER_IP}\\RasRemote",
      "remote_staging_path": "/mnt/RasRemote",
      "use_ssh_client": true,
      "cores_total": 8,
      "cores_per_plan": 4,
      "preprocess_on_host": true,
      "max_runtime_minutes": 60,
      "queue_priority": 3,
      "enabled": true
    }
  ]
}
```

---

## Execution Order

### Server 1: MediaQuad (192.168.3.2)
1. [ ] SSH into Proxmox: `ssh root@192.168.3.2`
2. [ ] Query resources (CPU, RAM, storage)
3. [ ] Download container template
4. [ ] Create LXC container with Docker support
5. [ ] Install Docker in container
6. [ ] Download HEC-RAS Linux binaries
7. [ ] Build all 4 Docker images
8. [ ] Configure SSH access
9. [ ] Configure Samba share
10. [ ] Test from Windows
11. [ ] Record container IP: _______________

### Server 2: CLB-02 (192.168.3.6)
(Same steps as above)

### Server 3: CLB-03 (192.168.3.20)
(Same steps as above)

### Final Steps
1. [ ] Update RemoteWorkers.json with container IPs
2. [ ] Run notebook 23 with all workers enabled
3. [ ] Verify parallel execution across all 3 servers

---

## Resource Allocation Summary

| Server | Host Cores | Container Cores | Host RAM | Container RAM (50%) |
|--------|------------|-----------------|----------|---------------------|
| MediaQuad | TBD | TBD | TBD | TBD |
| CLB-02 | TBD | TBD | TBD | TBD |
| CLB-03 | TBD | TBD | TBD | TBD |

---

## Estimated Time

| Phase | Time |
|-------|------|
| Phase 1: Gather info | 15 min |
| Phase 2: Create containers (x3) | 30 min |
| Phase 3: Build images (x3) | 45 min (parallel download/build) |
| Phase 4: SSH setup | 15 min |
| Phase 5: Samba setup | 15 min |
| Phase 6: Test & config | 15 min |
| **Total** | **~2-3 hours** |

---

## Questions Before Proceeding

1. **Confirm approach:** LXC containers (recommended) or full VMs?
2. **Static IPs:** Should containers get static IPs or use DHCP?
3. **Default HEC-RAS version:** Build all 4 versions, or just 6.6 for initial testing?
4. **Existing containers:** Any existing VMs/containers to avoid conflicts with VMID 200?
