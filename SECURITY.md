# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you find a security vulnerability, please report it by opening an issue on GitHub. Do NOT disclose vulnerabilities in public issues.

We aim to respond within 48 hours and will provide updates on the progress of fixing any reported issues.

## Security Considerations

This project handles:
- **OpenCollective API tokens** — Stored locally, never committed to git
- **Hetzner account credentials** — Stored locally, never committed to git

### Best Practices

1. **Never commit secrets** — The `.env` file is gitignored. Use `.env.example` as a template.
2. **Rotate tokens regularly** — Regenerate API tokens periodically
3. **Use environment variables** — Never hardcode credentials in code
4. **Review before pushing** — Check that `opencode.json` and `.env` aren't accidentally staged

## License

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

   2. Grant of Copyright License.

   3. Grant of Patent License.

   4. Redistributions.

   5. Submission of Contributions.

   6. Trademarks.

   7. Disclaimer of Warranty.

   8. Limitation of Liability.

   9. Accepting Warranty or Additional Liability.
```

See the full LICENSE file for details.
