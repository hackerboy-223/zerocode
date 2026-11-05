# Security Policy

## Supported versions

Security fixes are applied to the latest version on the `main` branch. ZeroCode is currently pre-1.0; users should expect breaking changes and review release notes before upgrading.

## Reporting a vulnerability

Please do not publish exploitable vulnerabilities in public issues.

Report security concerns privately through GitHub's **Report a vulnerability** feature on this repository. Include:
- the affected version or commit;
- the operating system and Python version;
- concise reproduction steps;
- the potential impact.

Do not include real API keys, passwords, private keys, or personal data in a report.

## Important execution boundary

ZeroCode can execute shell commands with the permissions of the operating-system account running it. Its file-tool restrictions do not sandbox shell processes, MCP servers, or code launched by those processes. Approval mode reduces accidental execution but is not an operating-system security boundary.

Use a disposable virtual machine or container for untrusted repositories. Avoid `--yolo` and `/full-stack` when working with untrusted code. Never expose production credentials to an agent session.

## Built-in defense-in-depth controls

ZeroCode enforces several layers of protection by default:
- **DLP secret redaction (`security.redact_secrets`)**: Tool outputs are automatically scanned and redacted before being added to session history or sent to upstream model providers (PEM private keys, OpenAI/OpenRouter/NVIDIA/GitHub/AWS/Google/Groq/HuggingFace/Slack tokens, `Bearer` headers, and database DSN passwords).
- **Catastrophic shell firewall (`security.check_dangerous_command`)**: Destructive host commands (`rm -rf /`, `rm -rf ~`, fork bombs, `mkfs`, raw `dd` writes to `/dev/*`, recursive `chmod` on `/`) are blocked even in `allow` / `--yolo` mode.
- **Subprocess environment isolation**: Provider API keys (`PROVIDER_KEY_ENVS`) are stripped from `bash` subprocesses and MCP server processes so untrusted scripts or tests cannot exfiltrate them from `os.environ`.
- **Workspace & secret boundary**: `read`, `write`, `edit`, `list`, `grep` (including `ripgrep --no-follow`), and `/undo` checkpoints block access to secret files (`.env`, `.ssh`, `.aws`, `.gnupg`, `*.pem`, `*.key`, etc.) and reject symlinks or paths escaping the workspace.
- **SSRF protection**: `fetch` and `web_search` validate every URL and redirect hop, blocking loopback, private, link-local, unspecified (`0.0.0.0`/`::`), IPv4-mapped IPv6 addresses, and cloud metadata hostnames (`169.254.169.254`, `metadata.google.internal`).

## Provider endpoint protection

Provider API keys are sent only to the configured provider endpoint. Custom base URLs are restricted to the provider's official HTTPS hostname; Ollama is restricted to loopback addresses. HTTP redirects are not followed for inference or model discovery, preventing credentials from being forwarded to an unexpected redirect destination.

Free model endpoints are not automatically private. Some upstream providers log prompts and outputs or use them to improve services. Do not send API keys, private source code, credentials, personal data, or other confidential information to free endpoints unless the provider's current terms explicitly meet your requirements.
