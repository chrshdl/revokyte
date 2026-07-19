# Contributing

Thanks for your interest in improving the instrument cluster!

## License and CLA

The project is licensed under **GPL-3.0-or-later**. In addition to the
GPL, all contributions require a Contributor License Agreement (CLA):

> By submitting a contribution (pull request, patch, or any other
> material) you grant the project maintainer (christian hedel) a
> perpetual, worldwide, non-exclusive, irrevocable, royalty-free license
> to use, modify, sublicense, and **relicense** your contribution,
> including distributing it under licenses other than the GPL.

**Why:** the maintainer also ships separately-licensed proprietary
add-ons that run in-process with this GPL code. As the sole copyright holder of the GPL codebase, the
maintainer can lawfully distribute that combination. Accepting GPL-only
contributions without a relicensing grant would permanently remove that
ability — so the CLA is a hard requirement, not a formality. Opening a
pull request constitutes agreement.

If you prefer not to sign over relicensing rights, that's completely
fine — filing issues, testing, and documentation feedback are just as
valuable and need no CLA.

## Practicalities

- Python 3.12 (matches the Pi image's interpreter).
- `uv venv && uv sync`, then `uv run pytest` — the suite must be green.
- Match the surrounding code style; no per-file license headers.
