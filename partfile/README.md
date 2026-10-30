# partfile

A `.parts` manifest describes a file as a list of SHA-256-hashed chunks plus
URLs where those bytes live. `partfile get` pulls each chunk from whichever
source has a valid copy, verifies it, and assembles the file. Pure Python
standard library, no dependencies.

```bash
# Publish: describe a file and list where it's hosted
python3 partfile.py create ubuntu.iso \
    --url https://mirror-a.example/ubuntu.iso \
    --url https://mirror-b.example/ubuntu.iso

# Download from a manifest (local path or URL)
python3 partfile.py get ubuntu.iso.parts

# Or ask for it by name via an index ({"files": {"ubuntu.iso": "ubuntu.iso.parts"}})
python3 partfile.py get ubuntu.iso --index https://host.example/index.json
#   (or set PARTFILE_INDEX=url1:url2)

python3 partfile.py info ubuntu.iso.parts
```

- Chunks download in parallel (`-j N`) and are spread randomly across mirrors.
- Every chunk is hash-checked, so a broken or malicious mirror gets skipped.
- An interrupted download resumes from `NAME.partial`.
- Chunks can also list their own `urls` for sources that host individual pieces.
- Works with servers that ignore HTTP Range requests (slower, but correct).
