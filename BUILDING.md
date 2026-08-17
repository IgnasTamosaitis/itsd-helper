# Building the Windows installer

The release installer is a per-user MSI containing a single PyInstaller-built
Windows executable. The executable bundles Python and the packages from
`requirements.txt`; target machines do not need Python or .NET.

## Local build prerequisites

- Windows 10 or 11
- Python 3.11 or later
- .NET SDK 8 or later

From the repository root, run:

```powershell
.\packaging\build_installer.ps1
```

The script reads `version.txt`, installs the Python build dependencies, creates
the application icon and version metadata, builds the executable, and compiles
the MSI with WiX Toolset. The result is:

```text
dist\installer\Jira-Reminders-x.y.z.msi
```

Use `-SkipDependencyInstall` when the Python dependencies are already present.
Use `-Version 1.3.0` to override `version.txt` for a test build.

### Code signing

The local test MSI is unsigned. Before company-wide distribution, sign both the
executable and MSI with the Girteka Authenticode code-signing certificate:

```powershell
.\packaging\build_installer.ps1 `
  -SigningCertificateThumbprint "CERTIFICATE_SHA1_THUMBPRINT"
```

The certificate must be available to the build user and `signtool.exe` must be
installed from the Windows SDK. The build script applies SHA-256 signatures and
a trusted timestamp to both artifacts. A signed installer avoids the **Unknown
publisher** warning and allows recipients to verify that the package came from
Girteka.

## Release build

Pushing a tag such as `v1.3.0` runs
`.github/workflows/build-installer.yml`. The workflow:

1. builds the MSI on a clean Windows runner;
2. publishes it as a workflow artifact; and
3. creates the GitHub release with the MSI already attached.

Do not publish a release before pushing the tag. The workflow deliberately waits
until the MSI is ready so installed copies cannot discover an incomplete release.
If you want to prepare a custom title and notes beforehand, create a **draft**
release for the tag; the workflow attaches the MSI and publishes that draft only
after the build succeeds. If no draft exists, it creates the release with
automatically generated notes.

## Installer behavior

- installs to `%LOCALAPPDATA%\Girteka\Jira Reminders`;
- creates Desktop, Start menu, and Startup shortcuts;
- launches the app after the first installation;
- upgrades older MSI versions in place;
- registers with Windows Installed Apps for standard uninstall;
- keeps user data in `%USERPROFILE%\.jira-reminders` when uninstalled.
