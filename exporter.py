#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "psutil>=5.9",
#     "pyyaml>=6.0",
# ]
# ///
"""
macOS Process Exporter for Prometheus.

Exposes per-process-group CPU and memory (RSS) metrics in
Prometheus exposition format. Designed for macOS where /proc doesn't exist.

Uses psutil for cross-platform process introspection.

Run with: uv run --script exporter.py [config_path]

Metrics exposed:
  Per-process group (labeled by group name):
  - macos_process_cpu_user_seconds_total (counter)
  - macos_process_cpu_system_seconds_total (counter)
  - macos_process_memory_rss_bytes (gauge)
  - macos_process_memory_vms_bytes (gauge)
  - macos_process_num_procs (gauge)
  - macos_process_num_threads (gauge)

  System-level:
  - macos_system_load_average{interval="1m|5m|15m"} (gauge)
  - macos_system_cpu_count (gauge)
  - macos_system_memory_total_bytes (gauge)
  - macos_system_memory_available_bytes (gauge)
  - macos_system_memory_used_bytes (gauge)
  - macos_system_memory_percent (gauge)
  - macos_system_swap_used_bytes (gauge)
  - macos_system_swap_total_bytes (gauge)
  - macos_system_disk_read_bytes_total (counter)
  - macos_system_disk_write_bytes_total (counter)
  - macos_system_disk_read_count_total (counter)
  - macos_system_disk_write_count_total (counter)

Note: Per-process disk I/O (io_counters()) is not available on macOS via psutil.
      System-wide disk I/O is provided instead for correlation with CPU spikes.
"""

import os
import re
import sys
import signal
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import psutil
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macos-process-exporter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yml"


def load_config(path: Path) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Compile regexes once
    for group in cfg.get("process_groups", []):
        group["_compiled"] = re.compile(group["cmdline_regex"])
    return cfg


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Collects process metrics on each scrape."""

    def __init__(self, config: dict):
        self.config = config
        self.groups = config.get("process_groups", [])

    def collect(self) -> dict:
        """Return a dict of group_name -> metrics dict."""
        results = {g["name"]: self._empty_metrics() for g in self.groups}

        for proc in psutil.process_iter(
            ["pid", "name", "cmdline", "cpu_times", "memory_info", "num_threads"]
        ):
            try:
                info = proc.info
                cmdline_str = " ".join(info["cmdline"] or [])
                if not cmdline_str:
                    continue

                for group in self.groups:
                    if group["_compiled"].search(cmdline_str):
                        m = results[group["name"]]
                        m["num_procs"] += 1
                        m["num_threads"] += info.get("num_threads") or 0

                        cpu_times = info.get("cpu_times")
                        if cpu_times:
                            m["cpu_user_seconds"] += cpu_times.user
                            m["cpu_system_seconds"] += cpu_times.system

                        mem = info.get("memory_info")
                        if mem:
                            m["memory_rss_bytes"] += mem.rss
                            m["memory_vms_bytes"] += mem.vms

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return results

    @staticmethod
    def _empty_metrics() -> dict:
        return {
            "num_procs": 0,
            "num_threads": 0,
            "cpu_user_seconds": 0.0,
            "cpu_system_seconds": 0.0,
            "memory_rss_bytes": 0,
            "memory_vms_bytes": 0,
        }


# ---------------------------------------------------------------------------
# Prometheus exposition format
# ---------------------------------------------------------------------------

def format_metrics(results: dict) -> str:
    lines = []

    def metric(name, mtype, help_text, values):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        for labels, value in values:
            lines.append(f'{name}{{{labels}}} {value}')

    cpu_user = []
    cpu_system = []
    mem_rss = []
    mem_vms = []
    num_procs = []
    num_threads = []

    for group_name, m in sorted(results.items()):
        label = f'group="{group_name}"'
        cpu_user.append((label, m["cpu_user_seconds"]))
        cpu_system.append((label, m["cpu_system_seconds"]))
        mem_rss.append((label, m["memory_rss_bytes"]))
        mem_vms.append((label, m["memory_vms_bytes"]))
        num_procs.append((label, m["num_procs"]))
        num_threads.append((label, m["num_threads"]))

    metric("macos_process_cpu_user_seconds_total", "counter",
           "Total user CPU time in seconds", cpu_user)
    metric("macos_process_cpu_system_seconds_total", "counter",
           "Total system CPU time in seconds", cpu_system)
    metric("macos_process_memory_rss_bytes", "gauge",
           "Resident set size in bytes", mem_rss)
    metric("macos_process_memory_vms_bytes", "gauge",
           "Virtual memory size in bytes", mem_vms)
    metric("macos_process_num_procs", "gauge",
           "Number of processes in group", num_procs)
    metric("macos_process_num_threads", "gauge",
           "Number of threads in group", num_threads)

    # -----------------------------------------------------------------------
    # System-level metrics
    # -----------------------------------------------------------------------

    # Load averages
    load1, load5, load15 = os.getloadavg()
    lines.append("# HELP macos_system_load_average System load average")
    lines.append("# TYPE macos_system_load_average gauge")
    lines.append(f'macos_system_load_average{{interval="1m"}} {load1}')
    lines.append(f'macos_system_load_average{{interval="5m"}} {load5}')
    lines.append(f'macos_system_load_average{{interval="15m"}} {load15}')

    # CPU count (for context - load avg / cpu_count = saturation ratio)
    cpu_count = psutil.cpu_count()
    lines.append("# HELP macos_system_cpu_count Number of logical CPUs")
    lines.append("# TYPE macos_system_cpu_count gauge")
    lines.append(f"macos_system_cpu_count {cpu_count}")

    # Memory pressure
    vmem = psutil.virtual_memory()
    lines.append("# HELP macos_system_memory_total_bytes Total physical memory")
    lines.append("# TYPE macos_system_memory_total_bytes gauge")
    lines.append(f"macos_system_memory_total_bytes {vmem.total}")
    lines.append("# HELP macos_system_memory_available_bytes Available memory")
    lines.append("# TYPE macos_system_memory_available_bytes gauge")
    lines.append(f"macos_system_memory_available_bytes {vmem.available}")
    lines.append("# HELP macos_system_memory_used_bytes Used memory")
    lines.append("# TYPE macos_system_memory_used_bytes gauge")
    lines.append(f"macos_system_memory_used_bytes {vmem.used}")
    lines.append("# HELP macos_system_memory_percent Memory usage percentage")
    lines.append("# TYPE macos_system_memory_percent gauge")
    lines.append(f"macos_system_memory_percent {vmem.percent}")

    # Swap
    swap = psutil.swap_memory()
    lines.append("# HELP macos_system_swap_used_bytes Swap used")
    lines.append("# TYPE macos_system_swap_used_bytes gauge")
    lines.append(f"macos_system_swap_used_bytes {swap.used}")
    lines.append("# HELP macos_system_swap_total_bytes Swap total")
    lines.append("# TYPE macos_system_swap_total_bytes gauge")
    lines.append(f"macos_system_swap_total_bytes {swap.total}")

    # Disk I/O (system-wide, not per-process - per-process unavailable on macOS)
    disk = psutil.disk_io_counters()
    if disk:
        lines.append("# HELP macos_system_disk_read_bytes_total Total bytes read from disk (all processes)")
        lines.append("# TYPE macos_system_disk_read_bytes_total counter")
        lines.append(f"macos_system_disk_read_bytes_total {disk.read_bytes}")
        lines.append("# HELP macos_system_disk_write_bytes_total Total bytes written to disk (all processes)")
        lines.append("# TYPE macos_system_disk_write_bytes_total counter")
        lines.append(f"macos_system_disk_write_bytes_total {disk.write_bytes}")
        lines.append("# HELP macos_system_disk_read_count_total Total disk read operations (all processes)")
        lines.append("# TYPE macos_system_disk_read_count_total counter")
        lines.append(f"macos_system_disk_read_count_total {disk.read_count}")
        lines.append("# HELP macos_system_disk_write_count_total Total disk write operations (all processes)")
        lines.append("# TYPE macos_system_disk_write_count_total counter")
        lines.append(f"macos_system_disk_write_count_total {disk.write_count}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class ReuseAddrHTTPServer(HTTPServer):
    allow_reuse_address = True


collector: MetricsCollector = None  # type: ignore


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics" or self.path == "/":
            results = collector.collect()
            body = format_metrics(results).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress per-request logging to avoid noise
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global collector

    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        log.error(f"Config file not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    port = config.get("listen_port", 9256)

    collector = MetricsCollector(config)

    server = ReuseAddrHTTPServer(("127.0.0.1", port), MetricsHandler)
    log.info(f"macOS Process Exporter listening on http://127.0.0.1:{port}/metrics")
    log.info(f"Tracking {len(config.get('process_groups', []))} process groups")

    def shutdown(sig, frame):
        log.info("Shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
