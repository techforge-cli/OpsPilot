from datetime import datetime, timezone


def parse_meminfo(text: str) -> dict:
    parsed = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parts = value.strip().split()
        number = parts[0].rstrip("kB").strip() if parts else ""
        try:
            parsed[key] = int(number)
        except ValueError:
            parsed[key] = 0
    return {
        "mem_total_kb": parsed.get("MemTotal", 0),
        "mem_available_kb": parsed.get("MemAvailable", 0),
        "swap_total_kb": parsed.get("SwapTotal", 0),
        "swap_free_kb": parsed.get("SwapFree", 0),
    }


def parse_loadavg(text: str) -> dict:
    parts = text.split()
    try:
        return {
            "one_minute": float(parts[0]),
            "five_minute": float(parts[1]),
            "fifteen_minute": float(parts[2]),
        } if len(parts) >= 3 else {}
    except (ValueError, IndexError):
        return {}


def parse_df(text: str) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip()]
    rows = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 7:
            rows.append({
                "filesystem": parts[0],
                "size_bytes": int(parts[1]),
                "used_bytes": int(parts[2]),
                "available_bytes": int(parts[3]),
                "mounted_on": parts[6],
            })
    return rows


def collect_native_snapshot(shell) -> dict:
    commands = {
        "loadavg": "cat /proc/loadavg",
        "meminfo": "cat /proc/meminfo",
        "df": "df -B1 -P",
        "ps": "ps -eo pid,ppid,user,pcpu,pmem,comm= --sort=-pcpu | head -30",
        "journal": "journalctl --since '5 minutes ago' -p err -o short 2>/dev/null | tail -50",
    }
    native_output = {name: shell.run(command) for name, command in commands.items()}
    memory = native_output["meminfo"][1]
    loadavg = native_output["loadavg"][1].strip()
    df = native_output["df"][1]
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "load": parse_loadavg(loadavg),
            "memory": parse_meminfo(memory),
            "disk": {"filesystems": parse_df(df)},
        },
        "processes": native_output["ps"][1],
        "recent_errors": native_output["journal"][1],
        "commands": {name: code for name, (code, _, _, _) in native_output.items()},
    }
