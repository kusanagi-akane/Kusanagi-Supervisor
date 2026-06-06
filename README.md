# Kusanagi Supervisor

Kusanagi Supervisor is a single-file Python CLI supervisor for running and monitoring multiple Python scripts from one terminal.

It is designed for cases where you need to keep several `.py` programs alive at the same time, each with its own working directory, arguments, environment variables, logs, and restart policy.

## Features

- Start, stop, and restart individual Python scripts
- Start or stop all configured scripts
- Show status, PID, CPU usage, memory usage, restart count, crash count, and uptime
- Tail recent log lines for each script
- Listen to live log output
- Hot reload the configuration file
- Automatically restart crashed scripts
- Limit repeated restarts to avoid tight crash loops
- Support custom working directories, command-line arguments, and environment variables

## Requirements

- Python 3.10 or newer
- `psutil` for CPU and memory metrics

Install dependencies:

```powershell
pip install -r requirements.txt
```

Kusanagi Supervisor can still run without `psutil`, but CPU and memory fields will show `N/A`.

## Quick Start

```powershell
python main.py
```

On first run, Kusanagi Supervisor creates:

- `supervisor_config.json`
- `logs/`

## Configuration

`supervisor_config.json` is a JSON object. Each key is a script profile name, and each value describes how that script should be launched.

Example:

```json
{
    "worker-a": {
        "path": "./services/worker_a",
        "file": "main.py",
        "enabled": true,
        "auto_restart": true,
        "args": ["--mode", "prod"],
        "env": {
            "APP_ENV": "production"
        }
    },
    "crawler-1": {
        "path": "D:/projects/crawler",
        "file": "run.py",
        "enabled": true,
        "auto_restart": true,
        "args": ["--limit", "100"],
        "env": {}
    }
}
```

## Configuration Fields

- `path`: Working directory for the script. Relative paths are resolved from the project directory.
- `file`: Python file to execute. It can be relative to `path` or an absolute path.
- `enabled`: Whether the script should be allowed to start.
- `auto_restart`: Whether the script should restart automatically after an unexpected exit.
- `args`: Command-line arguments passed to the script.
- `env`: Extra environment variables merged into the current environment.

## Commands

Run these commands inside the Kusanagi Supervisor prompt.

- `help`: Show available commands
- `scripts`: List configured script profiles
- `status`: Show process and resource status
- `monitor`: Open the auto-refreshing status view
- `start <name>`: Start one script
- `stop <name>`: Stop one script
- `restart <name>`: Restart one script
- `startall`: Start all enabled scripts
- `stopall`: Stop all running scripts
- `log <name> [N]`: Show the last N log lines, defaulting to 50
- `listen <name> on`: Stream live log output
- `listen <name> off`: Stop live log streaming
- `add`: Add a script profile interactively
- `edit <name>`: Edit a script profile interactively
- `remove <name>`: Remove a script profile
- `enable <name>`: Enable a script profile
- `disable <name>`: Disable a script profile
- `config`: Show all script profile details
- `clear`: Clear the terminal
- `exit`: Stop all scripts gracefully and exit

## Logs

Each script writes to its own daily log file:

```text
logs/<name>/YYYY-MM-DD.log
```

Kusanagi Supervisor writes its own log files to:

```text
logs/supervisor/
```

## Auto Restart

When a script exits unexpectedly and `auto_restart` is `true`, Kusanagi Supervisor starts it again.

To prevent fast crash loops, restarts are rate-limited by `RESTART_LIMIT` and `RESTART_WINDOW` in `main.py`.

## Development

Run a syntax check:

```powershell
python -B -c "import ast, pathlib; ast.parse(pathlib.Path('main.py').read_text(encoding='utf-8')); print('syntax ok')"
```

Run tests:

```powershell
python -B -m unittest discover -s tests
```

## Project Structure

- `main.py`: Kusanagi Supervisor
- `supervisor_config.json`: Runtime configuration file, created on first run
- `logs/`: Runtime log directory
- `requirements.txt`: Python dependencies
- `tests/`: Basic unit tests

## Notes

- `path` must exist and must be a directory.
- `file` must exist and must point to a Python file.
- `args` should be a JSON array.
- `env` values are converted to strings.
- On Windows, Kusanagi Supervisor attempts to enable UTF-8 console output for cleaner display.

## License

MIT License

## Contributing

Issues, suggestions, and pull requests are welcome.
