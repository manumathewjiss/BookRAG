# Sanskrity - Local Backup & Disaster Recovery

## Overview

The Sanskrity system now includes comprehensive local backup capabilities to ensure data resilience even if MongoDB Atlas is unavailable.

## Backup Components

### 1. Uploaded Files Backup
**Location:** `data/uploads/`

All user-uploaded PDFs, DOCX, and TXT files are automatically saved locally when processed.

**Configuration:**
```python
KEEP_UPLOADED_FILES = True  # In config.py
```

**Usage:**
- Files are saved with their original names
- Accessible even if MongoDB is down
- Can be re-processed if needed

### 2. Vector Data Backup
**Location:** `data/backups/`

MongoDB vector collections can be exported to local JSON files for disaster recovery.

**Manual Backup:**
```bash
SansAI/bin/python3 src/backup_vectors.py
```

This creates a timestamped backup of both:
- `scripture_vectors`
- `user_context_vectors`

**Restore from Backup:**
```bash
SansAI/bin/python3 src/backup_vectors.py restore <collection_name> <backup_dir>
```

Example:
```bash
SansAI/bin/python3 src/backup_vectors.py restore scripture_vectors data/backups/20260216_120000/scripture_vectors
```

### 3. Vector Cache (Future)
**Location:** `data/vectors/`

Reserved for local FAISS fallback if MongoDB becomes unavailable.

## Backup Schedule

**Automatic Backups:**
- Enabled by default (`AUTO_BACKUP_ENABLED = True`)
- Runs every 24 hours (`BACKUP_INTERVAL_HOURS = 24`)
- Can be disabled in `config.py`

**Manual Backups:**
Run anytime with:
```bash
SansAI/bin/python3 src/backup_vectors.py
```

## Storage Requirements

With 384-dim embeddings and ~41k scripture documents:

- **MongoDB:** ~165MB
- **Local Backups:** ~180MB per backup (JSON format has overhead)
- **Uploaded Files:** Varies (~1-10MB per file)

**Recommendation:** Keep 2-3 recent backups, delete older ones to save space.

## Disaster Recovery Procedure

### Scenario 1: MongoDB Data Loss

1. Stop the server
2. Clear MongoDB collections (if corrupted)
3. Restore from backup:
   ```bash
   SansAI/bin/python3 src/backup_vectors.py restore scripture_vectors data/backups/<timestamp>/scripture_vectors
   SansAI/bin/python3 src/backup_vectors.py restore user_context_vectors data/backups/<timestamp>/user_context_vectors
   ```
4. Restart server

### Scenario 2: Uploaded Files Lost

Files are in `data/uploads/` - just copy them back if needed.

### Scenario 3: Complete System Failure

1. Fresh installation
2. Copy `data/` directory from backup
3. Restore vectors to MongoDB
4. Start server

## Backup File Structure

```
data/
├── uploads/
│   ├── user_document1.pdf
│   ├── user_document2.docx
│   └── notes.txt
├── backups/
│   ├── 20260216_120000/
│   │   ├── scripture_vectors/
│   │   │   ├── scripture_vectors_20260216_120000_batch0000.json
│   │   │   ├── scripture_vectors_20260216_120000_batch0001.json
│   │   │   └── scripture_vectors_metadata.json
│   │   └── user_context_vectors/
│   │       └── ...
│   └── 20260215_120000/
│       └── ...
└── vectors/
    └── (reserved for FAISS cache)
```

## Gitignore

All backup directories are in `.gitignore` to prevent accidentally committing large data files:
- `data/uploads/`
- `data/backups/`
- `data/vectors/`

## Best Practices

1. **Regular Backups:** Run weekly backups manually or rely on auto-backup
2. **Test Restores:** Periodically test restore procedure
3. **Off-site Backup:** Copy `data/` directory to external drive/cloud monthly
4. **Monitor Space:** Check `data/` size regularly, delete old backups
5. **Backup Before Migration:** Always backup before running migration scripts

## Configuration Options

Edit `src/config.py`:

```python
# Local storage paths
UPLOAD_DIR = BASE_DIR / 'data' / 'uploads' 
BACKUP_DIR = BASE_DIR / 'data' / 'backups'
VECTOR_CACHE_DIR = BASE_DIR / 'data' / 'vectors'

# Storage settings  
KEEP_UPLOADED_FILES = True      # Save uploaded files
AUTO_BACKUP_ENABLED = True       # Enable auto-backup
BACKUP_INTERVAL_HOURS = 24       # Backup frequency
```

## Troubleshooting

**Backup fails with "Permission Denied":**
```bash
chmod -R 755 data/
```

**Restore fails with "Collection already exists":**
Clear the collection first:
```bash
SansAI/bin/python3 src/force_cleanup.py
```

**Backup files too large:**
- Backups are in JSON (human-readable but larger)
- For production, consider compressing: `tar -czf backup.tar.gz data/backups/<timestamp>/`

**Auto-backup not running:**
- Check server logs
- Ensure `AUTO_BACKUP_ENABLED = True` in config
- Restart server

## Security Notes

- Uploaded files may contain sensitive information
- Encrypt `data/` directory if needed
- Don't commit `data/` to git (already in `.gitignore`)
- Secure backup storage with appropriate permissions
