# Data acquisition

FlowLens uses the official KuaiRand-Pure release for Gate 2 validation.

- Source: https://zenodo.org/records/10439422
- Archive: `KuaiRand-Pure.tar.gz`
- Published MD5: `0820331067a3784d9691136f772b35a7`
- License in archive: CC BY-SA 4.0
- Local raw and extracted files are excluded from Git.

Download and verify:

```bash
curl -L --fail --retry 3 \
  -o data/raw/KuaiRand-Pure.tar.gz \
  https://zenodo.org/records/10439422/files/KuaiRand-Pure.tar.gz
md5 data/raw/KuaiRand-Pure.tar.gz
tar -xzf data/raw/KuaiRand-Pure.tar.gz -C data/extracted
```

Install the pinned Gate 2 environment and run the reproducible pipeline:

```bash
python -m venv .venv --system-site-packages
.venv/bin/python -m pip install -r requirements-gate2.txt
.venv/bin/python scripts/audit_kuairand_pure.py
.venv/bin/python scripts/prepare_kuairand_event_views.py
.venv/bin/python scripts/validate_kuairand_with_gx.py
.venv/bin/python scripts/build_gate2_notebook.py
```

The final two commands produce the Great Expectations validation report and an executed notebook plus HTML preview under `reports/data-quality/`.

Do not commit or redistribute the extracted data as part of this repository. Public reports must attribute the dataset and preserve its license requirements.
