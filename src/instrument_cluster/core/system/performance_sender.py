import json
import socket
import threading
import time


class PerformanceSender:
    def __init__(self, dest_ip: str = "", port=5005, interval=0.5):
        self.dest_ip = dest_ip
        self.port = port
        self.interval = interval
        self.running = False
        self._current_fps = 0.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def update_fps(self, fps):
        self._current_fps = fps

    def _loop(self):
        prev_idle, prev_total = self._get_cpu_load()

        while self.running:
            time.sleep(self.interval)

            # CPU load
            curr_idle, curr_total = self._get_cpu_load()
            delta_idle = curr_idle - prev_idle
            delta_total = curr_total - prev_total
            cpu_percent = 0.0
            if delta_total > 0:
                cpu_percent = 100.0 * (1.0 - delta_idle / delta_total)
            prev_idle, prev_total = curr_idle, curr_total

            # data packet
            data = {
                "fps": round(self._current_fps, 1),
                "temp": self._get_cpu_temp(),
                "freqs": self._get_all_cpu_freqs(),
                "load": round(cpu_percent, 1),
                "mem": self._get_memory_usage(),
            }

            if not self.dest_ip:
                continue
            try:
                self.sock.sendto(json.dumps(data).encode(), (self.dest_ip, self.port))
            except Exception as e:
                print(f"[Perf] Error: {e}")

    def _read_file_int(self, path):
        try:
            with open(path, "r") as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _get_cpu_temp(self):
        return self._read_file_int("/sys/class/thermal/thermal_zone0/temp") / 1000.0

    def _get_all_cpu_freqs(self):
        freqs = []
        for i in range(4):
            raw = self._read_file_int(
                f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            )
            freqs.append(raw // 1000)
        return freqs

    def _get_memory_usage(self):
        mem = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        mem[parts[0].strip(":")] = int(parts[1])
            total = mem.get("MemTotal", 0)
            available = mem.get("MemAvailable", 0)
            return (total - available) // 1024
        except Exception:
            return 0

    def _get_cpu_load(self):
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                fields = [float(x) for x in line.split()[1:]]
                return fields[3], sum(fields)
        except Exception:
            return 0, 0
