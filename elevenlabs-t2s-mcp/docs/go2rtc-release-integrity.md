# go2rtc release integrity

Research date: 2026-08-09

## Evidence

- The upstream latest release is `v1.9.14`, published on 2026-01-19, and its
  downloadable assets display SHA-256 digests. Source:
  [AlexxIT/go2rtc v1.9.14](https://github.com/AlexxIT/go2rtc/releases/tag/v1.9.14).
- GitHub's release asset response includes a `digest` field formatted as
  `sha256:<hex>`. Source:
  [GitHub REST API - release assets](https://docs.github.com/en/rest/releases/assets).
- A live read of the public
  [`releases/latest` endpoint](https://api.github.com/repos/AlexxIT/go2rtc/releases/latest)
  confirmed digests for every platform supported by this repository.

## Decision

Automatic installation pins go2rtc `v1.9.14` and the SHA-256 digest of each
supported asset. Downloaded bytes must match the pinned digest before an atomic
rename places them at the executable path. Updating go2rtc therefore requires an
intentional version-and-digest change with tests, rather than an unreviewed
runtime update through the mutable `latest` endpoint.

`GO2RTC_BIN` remains the explicit escape hatch for an operator-managed binary.
