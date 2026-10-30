# Animation engines (installed apps)

Large installs live outside the repo. Licence of the **app** is not the licence of **what we render**:
renders and projects we make are ours with every engine below.

| Engine | Version | Where | Licence | Commercial use | Notes |
|---|---|---|---|---|---|
| Synfig Studio (CLI `synfig`) | 1.5.5 | `/opt/homebrew/bin/synfig`, `/Applications/SynfigStudio.app` | GPL-3.0 | yes (output is ours) | The production engine today (D-031). Native arm64. |
| **Blender** | **5.2.3 LTS** (build 2026-10-22) | `/Applications/Blender.app` (907 MB, Homebrew cask `blender`) | GPL-2.0-or-later (`Resources/text/copyright.txt`) | yes | Native Apple Silicon (arm64). Run as `Blender --background --factory-startup --python script.py -- args`. No add-ons, no source changes. Its bundled Python 3.13 has no Pillow: image sizes must come from our data. |
| OpenToonz | 1.8.0 (official release, 2026-06-19) | `~/Applications/OpenToonz.app` + `~/ai-studio/tools/opentoonz-stuff` | BSD-3-Clause for OpenToonz's own code (bundled Qt 5.15 is LGPL) | yes | **Intel build under Rosetta 2** (no arm64 build exists upstream; the Homebrew cask is disabled because the pkg is unsigned). Run `tcomposer` with `-TOONZROOT`. Installed in the earlier spike (docs/spikes/opentoonz.md); not reinstalled. |

CMU mocap, models and so on are in `docs/MODELS.md`.
