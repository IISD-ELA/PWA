# PWA pipeline — installation

One-time setup. After this you can run the pipeline either through the [CLI](testing-cli.md) or from a [Jupyter notebook](testing-notebook.md).

Approximate time: 5–10 minutes (plus a short conda install if you don't already have GDAL).

## Prerequisites

- **Anaconda or Miniconda** — Python distribution and environment manager.
- **Git** — for cloning the three repos.
- That's it. The four PWA packages handle their own Python deps. GDAL (the one non-pip dep) gets installed via conda below.

## 1. Clone all three repos

The four PWA packages live across three GitHub repos. The `-b` flag below pins each clone to the branch with the latest refactor work — without it you'd land on `main` and miss everything.

```bash
git clone -b refactor/split-god-file https://github.com/IISD-ELA/PWA-hydro-conditioning-tools.git
git clone -b refactor/extract-pwa-raven https://github.com/IISD-ELA/PWA.git
git clone -b refactor/migrate-to-pwa-config https://github.com/IISD-ELA/PWA-modeling.git
```

After cloning, your working directory should look like:
```
your-workspace/
├── PWA/                              # contains pwa_raven and pwa_calibration
├── PWA-modeling/      # the orchestrator (this is what you install at the end)
└── PWA-hydro-conditioning-tools/     # contains pwa-tools (Step 0)
```

> **If you already have any of these repos cloned**, the fresh `git clone` will fail with "destination path already exists". Inside each existing clone, run instead:
> ```bash
> git fetch origin
> git checkout <branch-name>     # the branch listed above for each repo
> git pull
> ```
> Then continue with step 2.

## 2. Create the conda environment + install GDAL

```bash
conda create -n pwa python=3.12 -y
conda activate pwa
conda install -c conda-forge gdal -y
```

Verify:
```bash
gdalinfo --version    # should print "GDAL 3.x.x, released YYYY/MM/DD"
```

> **Why conda for GDAL?** GDAL is a C++ library with Python bindings; PyPI doesn't ship a working bundle for all platforms. Conda-forge does. This is the only library that needs conda — everything else comes via pip.

## 3. Install the four PWA packages in dependency order

```bash
pip install -e ./PWA-hydro-conditioning-tools
pip install -e ./PWA/pwa_raven
pip install -e ./PWA/pwa_calibration
pip install -e ./PWA-modeling
```

The last line installs the **orchestrator package** (`pwa`), which depends on the previous three. Installing it registers eight CLI commands on PATH (`pwa-hydrocondition`, `pwa-nc-processing`, `pwa-raven-inputs`, `pwa-calibrate` plus `pwa-init-*` variants) and exposes the umbrella `import pwa` namespace for notebook users.

Order matters: the orchestrator install resolves its declared dependencies (`pwa-tools`, `pwa-raven`, `pwa-calibration`) by name. Pip needs to already see them in the env — installing `./PWA-hydro-conditioning-tools` etc. first satisfies that.

## 4. Verify the install

```bash
pwa-hydrocondition --help        # should print usage banner
python -c "import pwa; print(pwa.__version__)"   # should print 0.1.0
```

If both work, you're done. Choose one of the two test-drive paths:

- **[testing-cli.md](testing-cli.md)** — drive the pipeline from the shell using the unified `pwa-*` commands.
- **[testing-notebook.md](testing-notebook.md)** — drive the pipeline from Python / Jupyter using the umbrella `import pwa` API.

Both paths run the same code; pick whichever fits how you'll actually use this day-to-day.

## Known gotchas

### macOS Raven binary (Step 3)

Step 3 (calibration) calls the Raven hydrological model executable. The Raven downloads page (http://raven.uwaterloo.ca/Downloads.html) only ships a "MacOS basic" binary that lacks NetCDF support — which the PWA pipeline requires. macOS users have to compile from source.

This is logged as **Q-006** in `client-questions.md`. For the test run today, you can complete Steps 0, 1, and 2 without Raven; Step 3 stops at the binary call.

### "Module not found" after install

If `pwa-hydrocondition --help` returns "command not found", check that:
1. You activated the conda env (`conda activate pwa`)
2. The four `pip install -e` lines all completed without errors
3. The conda env's `bin/` directory is on PATH (`which pwa-hydrocondition` should point inside the env)

### `pip install -e` says "already satisfied" without installing

If you previously installed a different version of one of the packages, pip might skip the editable install. Force it:
```bash
pip install --upgrade -e ./PWA-hydro-conditioning-tools
```

### Re-running install after pulling new commits

If you pull new code on any of the branches, the editable install picks it up automatically — you don't need to re-run `pip install`. Code changes are reflected on the next `import` or CLI invocation. The exception is changes to `pyproject.toml` or `console_scripts` declarations, which require a re-install of that specific package.
