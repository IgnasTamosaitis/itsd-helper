"""Generate a PyInstaller Windows version resource from version.txt."""
from __future__ import annotations

import sys
from pathlib import Path


TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Girteka'),
          StringStruct('FileDescription', 'Jira Reminders'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'JiraReminders'),
          StringStruct('OriginalFilename', 'JiraReminders.exe'),
          StringStruct('ProductName', 'Jira Reminders'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: create_version_info.py VERSION OUTPUT.txt")
    version = sys.argv[1].strip().lstrip("v")
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise SystemExit(f"Version must have three numeric parts: {version!r}")
    version_tuple = tuple(int(part) for part in parts) + (0,)
    output = Path(sys.argv[2]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        TEMPLATE.format(version=version, version_tuple=version_tuple),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
