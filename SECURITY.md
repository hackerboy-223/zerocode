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
