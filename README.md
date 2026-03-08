# 🤖 ShellAI

**Natural language Linux terminal assistant powered by [Ollama](https://ollama.ai)**

Turn plain English into safe, confirmed shell commands — entirely local, zero cloud dependency.

```
$ ai find files larger than 1GB
→ Request: find files larger than 1GB

  ┌──────────────────────────────────────────────┐
  │  find . -type f -size +1G                    │
  └──────────────────────────────────────────────┘

Execute? [y/N] y

./Downloads/ubuntu.iso
./Videos/rawfootage.mp4
```

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔤 Natural language input | Type what you want, get a shell command |
| 🛡️ Safety filter | Blocks `rm -rf /`, fork bombs, disk wipes, and more |
| ⚠️ Risk levels | Commands rated safe / medium / high — risky ones flagged automatically |
| 📖 Explain mode | `--explain` any command in plain English |
| 📜 History log | All requests and outcomes saved locally |
| 🎨 Colored output | Clean, readable terminal UI |
| ⚙️ Configurable | Switch models, URL, and behaviour with `ai --set` |
| 📦 Zero dependencies | Pure Python stdlib — no `requests`, no `click` |
| 🔒 100% local | Nothing leaves your machine |

---

## 📋 Requirements

- Linux (tested on Ubuntu 22.04+, Arch, Fedora)
- Python ≥ 3.10
- [Ollama](https://ollama.ai) running locally

---

## 🚀 Installation

### Option 1 — pip (recommended)

```bash
pip install shellai
```

### Option 2 — development install (editable)

```bash
git clone https://github.com/yourusername/shellai
cd shellai
pip install -e ".[dev]"
```

### Pull a model

```bash
ollama pull qwen2.5:7b       # default — fast, good quality
# or
ollama pull deepseek-coder   # great for system/dev tasks
```

### Start Ollama

```bash
ollama serve
```

---

## 🎮 Usage

### Translate natural language → shell command

```bash
ai find duplicate files
ai compress this folder
ai show running docker containers
ai install nginx
ai show disk usage by folder
ai monitor CPU and memory
ai list all open ports
```

### Explain a command

```bash
ai --explain tar -czvf backup.tar.gz ./myfolder
ai --explain find . -name "*.log" -mtime +7 -delete
```

### Manage history

```bash
ai --history          # show last 20 commands
ai --clear-history    # wipe history
```

### Model management

```bash
ai --models                         # list available Ollama models
ai --model deepseek-coder "..."     # use a different model for one request
ai --set model deepseek-coder:6.7b  # change default model permanently
```

### Configuration

```bash
ai --config                         # show all settings
ai --set model qwen2.5:7b
ai --set ollama_url http://192.168.1.5:11434
ai --set timeout 180
ai --set stream_explain true
```

---

## 🛡️ Safety System

Commands are classified into four risk levels:

| Level | Examples | Behaviour |
|---|---|---|
| ✅ safe | `ls`, `df`, `ps`, `grep` | Confirm → execute |
| 🟡 medium | `rm file.txt`, `systemctl stop` | Warn + explain + confirm |
| 🟠 high | `rm -rf ~/dir`, `curl … \| bash` | Warn prominently + explain + confirm |
| 🔴 critical | `rm -rf /`, fork bomb, `mkfs`, `dd` wipe | **Blocked — never executed** |

Patterns detected include:
- Recursive root deletion (`rm -rf /`)
- Disk format (`mkfs`)
- Disk wipe via `dd`
- Fork bomb `:(){ :|:& };:`
- Base64 obfuscated eval tricks
- Pipe-to-shell downloads (`curl … | bash`)
- System shutdown/reboot

---

## ⚙️ Configuration Reference

Config is stored in `~/.config/shellai/config.json`.

| Key | Default | Description |
|---|---|---|
| `ollama_url` | `http://localhost:11434` | Ollama API base URL |
| `model` | `qwen2.5:7b` | Default Ollama model |
| `timeout` | `120` | Seconds to wait for Ollama response |
| `history_limit` | `500` | Max entries kept in history |
| `stream_explain` | `true` | Stream tokens when explaining |
| `confirm_safe` | `true` | Ask confirmation for safe commands |
| `max_retries` | `2` | LLM retry attempts on bad output |

---

## 📁 Project Structure

```
shellai/
├── shellai/
│   ├── __init__.py        # version
│   ├── cli.py             # entry point & sub-commands
│   ├── ollama_client.py   # Ollama REST API client
│   ├── safety.py          # command safety filter
│   ├── executor.py        # subprocess runner
│   ├── history.py         # JSONL history log
│   ├── display.py         # colours & terminal UI
│   ├── prompts.py         # LLM prompt templates
│   └── config.py          # config load/save
├── tests/
│   ├── test_safety.py
│   └── test_cli.py
├── pyproject.toml
├── setup.py
├── LICENSE
└── README.md
```

---

## 🔬 Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check shellai/

# Type-check
mypy shellai/

# Build for PyPI
python -m build
```

---

## 📦 Publishing to PyPI

```bash
# Install build tools
pip install build twine

# Build
python -m build

# Upload to TestPyPI first
twine upload --repository testpypi dist/*

# Upload to PyPI
twine upload dist/*
```

---

## 🗺️ Roadmap

- [ ] Shell completion (bash/zsh/fish)
- [ ] Plugin system for custom safety rules
- [ ] `--dry-run` flag (generate but never execute)
- [ ] `--pipe` mode: `echo "find large files" | ai`
- [ ] Multi-step task chaining
- [ ] Context awareness (detect OS, installed tools)
- [ ] Interactive REPL mode (`ai shell`)
- [ ] Support for remote Ollama instances

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

## 🙏 Credits

Built on [Ollama](https://ollama.ai) — local LLM inference made easy.
