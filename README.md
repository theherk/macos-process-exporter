# macOS Process Exporter

A lightweight Prometheus exporter for tracking per-process CPU and memory on macOS. Built specifically for macOS where the standard Linux `process-exporter` (which requires `/proc`) doesn't work.

Comes with pre-built Grafana dashboards and a one-command installer.

## Why

Corporate security software (Microsoft Defender, ZScaler DLP, etc.) often consumes significant CPU on macOS, but it's difficult to quantify the actual long-term impact. This tool provides continuous monitoring with 15-second resolution, stored for up to 2 years, so you can measure exactly how much overhead these tools cost.

## What It Does

- Exposes per-process-group metrics in Prometheus exposition format on `http://127.0.0.1:9256/metrics`
- Tracks CPU time, RSS/VMS memory, process count, and thread count
- Also exposes system-level metrics: load averages, memory pressure, swap usage
- Process groups are defined by regex matching against the full command line
- Runs as a root LaunchDaemon for full visibility into all processes
- Pre-built Grafana dashboards auto-provisioned on install

## Prerequisites

- macOS (Apple Silicon or Intel)
- [Homebrew](https://brew.sh)
- [uv](https://docs.astral.sh/uv/) (install via `brew install uv`, or `mise use -g uv`, or `pipx install uv`)

## Quick Start

```bash
git clone https://github.com/theherk/macos-process-exporter.git
cd macos-process-exporter
chmod +x install.sh
./install.sh
```

The installer will:
1. Install `prometheus` and `grafana` via Homebrew
2. Create `config.yml` from the example (edit to customize)
3. Symlink Prometheus config into the Homebrew prefix
4. Configure Grafana to auto-provision dashboards
5. Generate a `run.sh` wrapper for your environment
6. Install and start a root LaunchDaemon
7. Start Prometheus and Grafana

After install, open Grafana at the URL shown by the installer (default http://localhost:3000, or http://localhost:3001 if port 3000 was occupied). Default login is admin/admin.

The example config tracks Microsoft Defender, ZScaler DLP, and Spotlight out of the box. If your machine runs these, you'll see data immediately with no edits needed.

## Configuration

The example config (`config.example.yml`) ships with groups for Microsoft Defender, ZScaler, and Spotlight. The installer copies it to `config.yml` on first run. If those are what you want to track, no changes are needed.

To track different processes, edit `config.yml`:

```yaml
process_groups:
  - name: my_app
    cmdline_regex: "my-application"
  - name: my_app_helper
    cmdline_regex: "my-app-helper"
  - name: my_app_total
    cmdline_regex: "my-application|my-app-helper"
```

Each group aggregates all matching processes. The `cmdline_regex` is a Python regex applied to the full command line (all arguments joined with spaces).

After editing, restart the exporter:

```bash
sudo launchctl unload /Library/LaunchDaemons/com.local.macos-process-exporter.plist
sudo launchctl load /Library/LaunchDaemons/com.local.macos-process-exporter.plist
```

## Architecture

```
[exporter.py]  -->  :9256/metrics   (Python via uv, uses psutil)
      ^
      |  scrapes every 15s
[prometheus]   -->  :9090           (2-year retention)
      ^
      |  data source
[grafana]      -->  :3001           (auto-provisioned dashboards)
```

All services bind to `127.0.0.1` only.

## Metrics

### Per-process group (labeled by `group`)

| Metric | Type | Description |
|--------|------|-------------|
| `macos_process_cpu_user_seconds_total` | counter | User CPU time |
| `macos_process_cpu_system_seconds_total` | counter | System CPU time |
| `macos_process_memory_rss_bytes` | gauge | Resident set size |
| `macos_process_memory_vms_bytes` | gauge | Virtual memory size |
| `macos_process_num_procs` | gauge | Process count |
| `macos_process_num_threads` | gauge | Thread count |

### System-level

| Metric | Type | Description |
|--------|------|-------------|
| `macos_system_load_average` | gauge | Load average (1m/5m/15m) |
| `macos_system_cpu_count` | gauge | Logical CPU count |
| `macos_system_memory_total_bytes` | gauge | Total physical memory |
| `macos_system_memory_available_bytes` | gauge | Available memory |
| `macos_system_memory_used_bytes` | gauge | Used memory |
| `macos_system_memory_percent` | gauge | Memory usage % |
| `macos_system_swap_used_bytes` | gauge | Swap used |
| `macos_system_swap_total_bytes` | gauge | Swap total |
| `macos_system_disk_read_bytes_total` | counter | Total bytes read from disk (all processes) |
| `macos_system_disk_write_bytes_total` | counter | Total bytes written to disk (all processes) |
| `macos_system_disk_read_count_total` | counter | Total disk read operations |
| `macos_system_disk_write_count_total` | counter | Total disk write operations |

## Dashboards

Two dashboards are auto-provisioned:

**Security Software Impact** - CPU and memory breakdown for Defender and ZScaler, stacked and per-component.

**System Health & Spotlight** - Load averages, memory pressure, swap, and Spotlight indexing overhead.

These dashboards are built for the groups defined in `config.example.yml`. If you rename or remove process groups in your `config.yml`, you'll need to update the dashboard queries to match. The JSON files in `grafana/dashboards/` are editable, or you can modify them directly in the Grafana UI (they're marked editable).

## Overhead

Each scrape takes ~60ms and occurs every 15 seconds. Total CPU cost is approximately 0.4% of one core. The exporter runs with `nice 10` and `LowPriorityIO` so it won't interfere with your workload.

## File Layout

```
.
├── exporter.py                    # The exporter (PEP 723 inline deps, run via uv)
├── config.example.yml             # Example process groups (copied to config.yml on install)
├── config.yml                     # Your customized config (generated, git-ignored)
├── install.sh                     # One-command installer
├── uninstall.sh                   # Clean removal
├── prometheus.yml                 # Prometheus scrape config (symlinked into brew prefix)
├── prometheus.args.template       # Prometheus flags template (resolved on install)
├── prometheus.args                # Generated Prometheus flags (git-ignored)
├── run.sh                         # Generated wrapper for launchd (git-ignored)
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml
│   │   └── dashboards/
│   │       ├── default.yml.template
│   │       └── default.yml        # Generated (git-ignored)
│   └── dashboards/
│       ├── security-software.json
│       └── system-health.json
├── exporter.log                   # Runtime stdout (git-ignored)
└── exporter.err                   # Runtime stderr (git-ignored)
```

## Uninstall

```bash
./uninstall.sh
```

## License

MIT
