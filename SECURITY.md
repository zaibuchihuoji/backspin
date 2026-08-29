# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately — do **not** open a public
issue. Use [GitHub's private vulnerability reporting](
https://github.com/zaibuchihuoji/backspin/security/advisories/new), or email
the maintainers. We aim to respond within 72 hours.

## Threat model worth knowing about

backspin records **full prompts and completions** — including anything your
agent, your tools, or your users put into them. Treat every `*.backspin.jsonl`
file as sensitive as the conversation it captured:

- **Secrets in recordings.** API keys that appear inside prompts, tool
  arguments, error messages or tracebacks are recorded verbatim unless you
  pass a `redact=` function. See *Keeping secrets out of recordings* in the
  README and `backspin.redaction`. The proxy never records Authorization /
  x-api-key headers, but cannot know a key is embedded in a prompt.
- **Share files.** `backspin share` inlines the entire run into one HTML
  file. Sending that file is sending the raw conversation.
- **Local-only surfaces.** The viewer and proxy bind to `127.0.0.1` by
  default. Do not expose them to a network without an auth layer — they are
  debug tools, not hardened services.

## Supported versions

Only the latest minor release receives security fixes.
