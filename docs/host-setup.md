# HPZ440 Host Setup

One-time steps on the HPZ440 itself (Ubuntu 24.04 LTS), run over SSH as a user with sudo. These are manual because they need sudo, a reboot, and a judgement call on driver versions. After this, everything else is driven from the workstation through the `hpz440` Docker context.

## 1. Physical install

Seat the RTX 3060, connect its PCIe power lead, and boot. Confirm the OS sees it:

```bash
lspci | grep -i nvidia
```

Expected: one line naming an NVIDIA device. If nothing appears, check seating and power before continuing.

## 2. NVIDIA driver

```bash
sudo ubuntu-drivers install
sudo reboot
```

After the reboot:

```bash
nvidia-smi
```

Expected: a table showing the RTX 3060 and a driver version of 550 or newer.

## 3. NVIDIA Container Toolkit

Commands from NVIDIA's installation guide for apt-based distributions:
<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>. Check that page if any step below fails; the repository URL or key location may have changed.

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Confirm Docker now lists the runtime:

```bash
docker info --format '{{range $k,$v := .Runtimes}}{{$k}} {{end}}'
```

Expected: the output includes `nvidia`.

## 4. Verify from the workstation

```powershell
pwsh -NoProfile -File scripts/check-gpu.ps1
```

Expected: `nvidia-smi` output from inside a container, then `GPU check passed on context 'hpz440'.`

## 5. Host directories

Create the directories that `compose.yaml` and the scripts bind-mount, owned by the SSH user so `scripts/fetch-model.ps1` can write there:

```bash
sudo mkdir -p /srv/llm/models /srv/llm/jarvis-data
sudo chown -R "$USER":"$USER" /srv/llm
```

If `.env` overrides `HOST_MODEL_DIR` or `HOST_JARVIS_DATA_DIR`, create those paths instead.
