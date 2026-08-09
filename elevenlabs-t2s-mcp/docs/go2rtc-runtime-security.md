# Managed go2rtc runtime security

Research and verification date: 2026-08-09

## Upstream contract

This repository pins go2rtc `v1.9.14`, so the runtime design is checked against that exact tag:

- [`v1.9.14` app configuration](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/internal/app/README.md)
  documents `${NAME}` environment substitution and the public default listeners.
- [`v1.9.14` schema](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/www/schema.json)
  defines `api.listen`, `username`, `password`, `local_auth`, `allow_paths`, and the protocol
  listener fields used here.
- [`v1.9.14` security guidance](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/README.md#security)
  warns that default ports are reachable from the local network, recommends loopback binding,
  and documents `local_auth` for authenticating localhost requests.

## Managed policy

When Sanpoloid generates and starts go2rtc itself:

- camera username and password are URL-encoded and supplied only through dedicated child-process
  environment variables; the generated YAML contains placeholders, not credential values;
- API credentials are random per launch, are omitted from object representations, and are supplied
  through process environment variables;
- the API binds to `127.0.0.1:1984`, requires Basic auth even from localhost, and allows only
  `/api` and `/api/streams`;
- RTSP binds to `127.0.0.1:8554` because the FFmpeg backchannel needs the local RTSP transport;
- WebRTC and SRTP listeners are disabled;
- all dynamic YAML string values use JSON-compatible quoting, and camera authority input rejects
  credentials, paths, queries, whitespace, and malformed IP/host values;
- config replacement is atomic. POSIX files are mode `0600`; Windows receives the containing user
  profile directory's inherited ACL;
- the child environment starts from a small runtime allowlist (paths, locale, temporary-directory,
  and platform variables) before the dedicated managed values are added; arbitrary parent
  variables are not inherited;
- stderr is not retained in a pipe or surfaced to MCP clients, avoiding credential-bearing daemon
  diagnostics and an unread-pipe deadlock;
- auto-start probes an already responding endpoint without credentials and refuses to reuse it;
  only the post-launch health check sends the per-launch Basic credentials;
- a managed URL must be plain HTTP on a loopback host at port 1984. Credentials never appear in
  that URL and API clients send the Authorization header explicitly.

## Runtime evidence

A hardware-free Windows smoke used the repository's pinned artifact selection and SHA-256
verification, generated a config with sentinel camera credentials, started go2rtc `v1.9.14`, and
then stopped it. It confirmed:

- authenticated `/api` health succeeded and an unauthenticated request returned HTTP 401;
- the owned TCP listeners were exactly `127.0.0.1:1984` and `127.0.0.1:8554`;
- no non-loopback TCP listener was owned by the process;
- ports 8555 and 8443 were not opened by the process;
- the generated config contained neither sentinel credential.

## Boundary

`GO2RTC_CONFIG`, an existing `GO2RTC_BIN`, or an independently running service is explicitly
operator-managed. For an external service, set `GO2RTC_AUTO_START=false`; Sanpoloid does not rewrite
or attest that service's bind, auth, binary, config, or credential lifecycle. A Basic-authenticated
external API can be selected with the paired `GO2RTC_API_USERNAME` and `GO2RTC_API_PASSWORD`
variables; partial credentials are rejected during configuration loading.

Process environment is an improvement over persistent YAML but is not a hardware-backed secret
store and may remain observable to the same OS account or an administrator. Real camera login,
FFmpeg audio transfer, Tapo backchannel behavior, mobile runtime behavior, and LAN adversarial E2E
were not proven by the hardware-free smoke.
