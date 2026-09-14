# Vendored Font: Monocraft

- **Font**: Monocraft
- **Version / Release Tag**: v4.2.1
- **License**: SIL Open Font License 1.1 (see [OFL.txt](./OFL.txt))
- **Source**: https://github.com/IdreesInc/Monocraft

## Reproducing the subset woff2

The Latin-subset WOFF2 font file `monocraft.woff2` (3.0 KB) was generated from `Monocraft.ttf` (v4.2.1) using `pyftsubset` from `fonttools`:

```bash
pyftsubset Monocraft.ttf \
  --unicodes="U+0020-007E,U+00A0-00FF,U+2010-2015,U+2018-2019,U+201C-201D,U+2026,U+2030,U+2039-203A,U+2044,U+20AC,U+2122" \
  --layout-features="" \
  --flavor=woff2 \
  --output-file=monocraft.woff2
```
