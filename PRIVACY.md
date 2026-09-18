# Privacy Policy

**Short version: Delfin collects nothing.**

Delfin is a local desktop tray application for Windows. It has no user accounts, no
telemetry, no analytics, no crash reporting and no advertising. It does not collect,
store or transmit your personal data.

Last updated: 2026-09-18

---

## What Delfin stores on your machine

Everything Delfin keeps lives in the folder where you put `dsh-tray.exe`. Nothing is
sent anywhere.

| File / folder | Contents |
|---|---|
| `settings.json` | Your preferences: UI language, startup-on-boot, update channel |
| `dsh.log` | Log output of the local `dsh` service |
| `.dsh.pid` | PID of the running local service, so Delfin can stop it again |
| `runtime/` | The locally managed copy of `dsh` installed by Delfin |

Delfin does not write anywhere else, does not touch the Windows registry for tracking
purposes, and does not create any identifier for you or your machine.

---

## Network access

Delfin makes exactly one kind of outbound request.

| Destination | Purpose | What is sent |
|---|---|---|
| `https://registry.npmjs.org/@deepseek-ai%2fdsh` | Read the latest published version of `dsh`, so the tray menu can tell you whether an update is available | Nothing. An unauthenticated `GET` with the static User-Agent `delfin`. |

There is no identifier, no machine ID, no usage data and no telemetry in that request —
it is the same request any `npm view` command would make, and the registry learns
nothing about you beyond your IP address, which is unavoidable for any HTTP request.

If you use the **update** action, Delfin runs `npm install` for the managed runtime,
which downloads packages from the npm registry in the normal way. This only happens
when you ask for it.

The `dsh` service itself listens on `http://127.0.0.1:<port>` (default `3080`), which
is reachable only from your own machine. Delfin opens that address in your browser when
you choose **Open**. Nothing is sent off your machine by doing so.

---

## Third parties

Delfin does not embed any third-party analytics, advertising, crash-reporting or
tracking SDK.

Delfin is a front-end for [DeepSeek Harness (`dsh`)](https://www.npmjs.com/package/@deepseek-ai/dsh),
which is a separate project with its own behaviour and its own privacy policy. What
that service does once running is outside Delfin's control.

---

## Required statement

Beyond the version lookup described above, **this program will not transfer any
information to other networked systems unless specifically requested by the user or the
person installing or operating it.**

---

## Changes

If this policy changes, the update will be committed to this repository and the date at
the top of this file will change accordingly.

## Contact

Open an issue at <https://github.com/konmins/delfin/issues>.

---

## 中文说明

**Delfin 不收集任何个人数据。**

- **本地存储**：`settings.json`（你的偏好设置）、`dsh.log`（服务日志）、`.dsh.pid`（服务进程号）、
  `runtime/`（Delfin 自行安装的 `dsh` 运行时）。这些文件都在 exe 所在的目录里，不会外传。
- **唯一的对外请求**：向公开的 npm registry 查询 `dsh` 的最新版本号，用于菜单里显示是否有更新。
  该请求是匿名的 `GET`，User-Agent 固定为 `delfin`，**不含任何标识符、使用数据或遥测**。
- **更新操作**：只有你主动点更新时，Delfin 才会调用 `npm install` 下载运行时。
- **本地服务**：`dsh` 只监听 `http://127.0.0.1:<端口>`，仅本机可访问。
- **无第三方追踪**：不内嵌任何分析、广告、崩溃上报或追踪 SDK。

除上述版本查询外，**本程序不会向其他联网系统传输任何信息，除非用户或安装/操作者明确请求**。
