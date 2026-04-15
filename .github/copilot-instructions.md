# Copilot instructions for `record`

## Project snapshot
- This is a **PlatformIO + Arduino** firmware project targeting **ESP32 DevKit V1**.
- Active environment is defined in [platformio.ini](../platformio.ini): `env:esp32doit-devkit-v1`, `framework = arduino`, `monitor_speed = 115200`.
- Current app code is a minimal scaffold in [src/main.cpp](../src/main.cpp) using Arduino lifecycle functions `setup()` and `loop()`.

## Architecture and code boundaries
- Keep runtime firmware entrypoint in [src/main.cpp](../src/main.cpp).
- Put reusable headers in [include/](../include/) and include them from `src` files.
- Put project-local reusable modules under [lib/<module>/](../lib/) (PlatformIO builds these as static libs).
- Keep generated build artifacts in `.pio/` untouched.
- Do not manually edit auto-generated VS Code config files in [.vscode/c_cpp_properties.json](../.vscode/c_cpp_properties.json) or [.vscode/launch.json](../.vscode/launch.json).

## Dependencies and integrations
- External dependency is declared in [platformio.ini](../platformio.ini):
  - `https://github.com/pschatzmann/arduino-audio-tools.git`
- Add new third-party libraries through `lib_deps` in [platformio.ini](../platformio.ini), not by committing downloaded source into `src`.

## Build, flash, monitor workflow
- Preferred local workflow is PlatformIO:
  - Build: `pio run`
  - Upload/flash: `pio run -t upload`
  - Serial monitor: `pio device monitor -b 115200`
  - Run tests (when tests exist): `pio test`
- In VS Code, use PlatformIO extension commands/tasks; this project recommends `platformio.platformio-ide` in [.vscode/extensions.json](../.vscode/extensions.json).

## Debugging workflow
- Use existing PlatformIO debug launch configs in [.vscode/launch.json](../.vscode/launch.json) (`PIO Debug*`).
- Keep `projectEnvName` aligned with environment names in [platformio.ini](../platformio.ini) when adding new targets.

## Code conventions specific to this repo
- Keep Arduino-style structure: hardware initialization in `setup()`, repeated logic in `loop()`.
- Avoid leaving template placeholders (`myFunction`) once real firmware logic is added.
- Favor small modules and headers instead of growing [src/main.cpp](../src/main.cpp) monolithically.
- Add tests under [test/](../test/) using PlatformIO test runner conventions when behavior becomes non-trivial.

## Agent guidance
- Before broad refactors, verify whether code is still scaffold-level or has grown into modules under `lib/`.
- When changing board/framework/serial settings, update [platformio.ini](../platformio.ini) first and treat `.vscode` files as generated outputs.
- If build issues involve include paths, check library resolution via `lib_deps` and `lib/` layout before editing source logic.
