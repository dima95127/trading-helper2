# Trading Helper APK

## Build via GitHub Actions

1. Create a new public repository on GitHub
2. Upload all files from this archive (keep folder structure)
3. Go to Actions tab - build starts automatically
4. Wait 30-60 minutes
5. Download artifact "trading-helper-apk"
6. Transfer .apk to phone and install

## Build via Linux/WSL

```bash
pip install buildozer cython==0.29.34
buildozer -v android debug
```

APK will be in bin/ folder.
