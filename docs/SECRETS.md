# Secrets and credentials

Tier 1 (GitHub-hosted emulator/simulator/editor lanes) needs **no secrets** except for Unity editor activation.
Everything below is optional and gates itself off when absent.

| Secret | Used by | Notes |
|---|---|---|
| `UNITY_EMAIL`, `UNITY_PASSWORD`, `UNITY_SERIAL` | `bench-unity.yml` | Same Pro-serial activation the backtrace-unity repository uses. Steps run sequentially inside one job so a single seat is enough. |
| `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY` | `bench-sauce.yml` | Same names as the backtrace-android repository. Region `us-west-1`; device ids from the Sauce Labs catalog (e.g. `Google_Pixel_9_Pro_XL_15_real_sjc1`). Real-device numbers are trends, never gates. |
| `BUILD_CERTIFICATE_BASE64_2026` | `bench-apple.yml` signed-size lane | base64 of the Apple distribution `.p12` (same secret name as backtrace-cocoa's deploy workflow). |
| `P12_PASSWORD_2026` | same | password of that `.p12`. |
| `BUILD_PROVISION_PROFILE_BASE64_2026` | same | base64 of the iOS `.mobileprovision`. The App Thinning Size Report needs an ad-hoc or development profile whose app id covers `io.backtrace.bench.*`; an App Store profile makes the lane report `unsupported` and the unsigned size numbers stand. |
| `MAC_BUILD_PROVISION_PROFILE_BASE64_2026` | reserved (macOS signed size) | base64 of the macOS `.provisionprofile`. |
| `KEYCHAIN_PASSWORD` | same | any random string; a temporary keychain is created and deleted per job. |
| `DISTRIBUTION_IDENTITY` | same | the signing identity name, e.g. `Apple Distribution: <team>`. |
| `HARNESS_DISPATCH_TOKEN` | SDK repositories → `bench-release-report.yml` | fine-grained PAT or GitHub App token with `actions: write` on this repository, used by SDK release workflows to send `repository_dispatch` (`sdk-release`). |

To create the base64 values locally (never commit the outputs):

```bash
base64 -i /path/to/distribution.p12 | pbcopy        # BUILD_CERTIFICATE_BASE64_2026
base64 -i /path/to/ios.mobileprovision | pbcopy     # BUILD_PROVISION_PROFILE_BASE64_2026
base64 -i /path/to/macos.provisionprofile | pbcopy  # MAC_BUILD_PROVISION_PROFILE_BASE64_2026
```

`gh secret set <NAME> --repo melekr/backtrace-benchmarks < file` also works. The `results` and `gh-pages` branches are written with the default `GITHUB_TOKEN` (`contents: write` only in the report job).
