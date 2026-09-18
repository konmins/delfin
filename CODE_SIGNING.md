# Code Signing Policy

Free code signing provided by [SignPath.io](https://signpath.io?utm_source=foundation&utm_medium=github&utm_campaign=delfin),
certificate by the [SignPath Foundation](https://signpath.org?utm_source=foundation&utm_medium=github&utm_campaign=delfin).

---

## What gets signed

Only the Windows executable `dsh-tray.exe` built by this repository's automated
build is code signed.

| | |
|---|---|
| Repository | <https://github.com/konmins/delfin> |
| Signed artifact | `dsh-tray.exe` (Windows x64) |
| Workflow | [`.github/workflows/build.yml`](.github/workflows/build.yml) — job `sign` |
| Trusted build system | GitHub Actions |
| Trigger | Pushing a `v*` tag |

The pipeline is `build → sign → release`. The release job runs **only if signing
succeeded**, so an unsigned binary is never published. The signed executable is packed
into `delfin-v<version>-win64.zip` together with `dsh-runner.cmd` (the launcher the
executable needs at runtime).

### Local builds are never signed

SignPath's `release-signing` policy has **Require trusted build system** enabled.
Binaries built on a developer machine cannot be submitted for signing, even by a
project approver. The signature on a released binary therefore guarantees that it was
produced by the workflow above from this repository's source.

### Manual approval

Every release requires **manual approval by a project approver** before SignPath will
sign it. A tag push alone does not produce a signed release.

---

## Team roles

Delfin is currently a single-maintainer project.

- **Committers and reviewers**: [@konmins](https://github.com/konmins)
- **Approvers** (authorized to approve signing requests): [@konmins](https://github.com/konmins)

Changes proposed by people who are not committers (i.e. pull requests) are reviewed by
a committer before merging. Every signing request is approved by an approver trusted to
decide whether a given release may be code signed.

All project members have **two-factor authentication enabled** on both GitHub and
SignPath.

---

## Privacy

Delfin collects no personal data and contains no telemetry of any kind. See
[PRIVACY.md](PRIVACY.md) for the full policy.

The only outbound request the application makes is an unauthenticated `GET` to the
public npm registry, used to look up the latest published version of `dsh` for the
update check. That request carries no identifier, no usage data and no telemetry.

Beyond that update lookup, this program will not transfer any information to other
networked systems unless specifically requested by the user or the person installing
or operating it.

---

## Verifying a signature

After downloading a release, you can confirm the signature yourself.

Right-click `dsh-tray.exe` → **Properties** → **Digital Signatures**. The signer should
read `SignPath Foundation`.

Or from the command line:

```powershell
Get-AuthenticodeSignature .\dsh-tray.exe | Format-List Status, SignerCertificate
```

`Status` should be `Valid`, and `SignerCertificate.Subject` should contain
`SignPath Foundation`.

---

## 中文说明

**代码签名政策**

本项目的 Windows 可执行文件 `dsh-tray.exe` 由
[SignPath.io](https://signpath.io?utm_source=foundation&utm_medium=github&utm_campaign=delfin)
提供免费代码签名服务，证书由
[SignPath Foundation](https://signpath.org?utm_source=foundation&utm_medium=github&utm_campaign=delfin)
提供。

- **只签 CI 产物**：签名策略启用了「要求受信任构建系统」，本机手工打包的 exe 无法送签。
  因此签名可以证明「这个二进制确实由本仓库的源码、经上述流水线构建而来」。
- **每次发布需人工批准**：仅打 tag 不会自动产生已签名的发布。
- **发布包不含未签名版本**：`release` 阶段以「签名成功」为前置条件，没签名就不发版。

**隐私**：Delfin 不收集任何个人数据，无遥测、无统计分析。唯一的对外请求是向公开的
npm registry 查询 `dsh` 的最新版本号（匿名 GET，不含任何用户信息）。详见
[PRIVACY.md](PRIVACY.md)。
