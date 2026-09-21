# Security & Privacy

Finance Assistant is local-first: your data lives in `.finance/` on your machine
and nothing is uploaded. This document is the full detail — the [README](../README.md#privacy--security)
has the summary.

## Design Principles

1. **Local-only**: All data lives in `.finance/` on your machine. No telemetry. No cloud sync. The only network calls are the opt-in ones listed under [Network calls](#network-calls-opt-in) — none send transactions, balances, or names.
2. **Structured summaries, not raw data**: Transaction amounts and categories are stored, not raw bank statements or login sessions.
3. **You own the delete button**: Every data category can be deleted individually or all at once.
4. **Encryption at rest**: Fernet AES-128-CBC + HMAC-SHA256 — the same authenticated encryption scheme used in production web services.
5. **Passphrase quality enforced**: The system rejects weak passphrases before encrypting (minimum 12 chars, character variety required), because a strong cipher with a weak key is still weak.
6. **Atomic writes**: Encrypted files are written to a `.enc.tmp` file first, then atomically renamed — a power failure or crash cannot leave a half-encrypted, unreadable file.
7. **File permissions**: `harden_permissions()` sets `.finance/` to `700` (owner-only directory) and all files to `600` (owner-only read/write). Other OS users on the same machine cannot read your data.
8. **Git guard**: On first session, `.finance/` is automatically added to `.gitignore` so financial data cannot be accidentally committed and pushed to a repository.
9. **Audit log**: Every significant data access (read, write, encrypt, export, delete) is logged to `audit/access_log.json` with a timestamp.
10. **Sanitize before sharing**: `sanitize_for_sharing(data)` strips all PII (names, employers, payees, addresses) before you share data to get help — financial amounts and structures are preserved.

## Encryption Details

```
Key derivation: PBKDF2-HMAC-SHA256
Iterations:     480,000 (NIST 2023 recommendation)
Salt:           16 bytes random per file (unique per encryption)
Cipher:         AES-128 in CBC mode (via Fernet)
MAC:            HMAC-SHA256 (Fernet built-in; prevents ciphertext tampering)
Encoding:       Base64url
Dependency:     pip install cryptography
```

Each file gets its own random salt. Two files encrypted with the same passphrase produce different ciphertexts — you cannot tell if two files contain the same data by comparing them.

The salt is stored alongside the ciphertext (standard practice — it only makes brute-force harder when combined with high iteration counts; it does not weaken the encryption).

## Encrypted Export & Backup

Backups can be encrypted before leaving your machine:

```python
# Encrypted backup — safe to store in cloud or email to yourself
export_all_data(passphrase="MyStr0ng!Passphrase")

# Plaintext export — keep offline only
export_all_data()
```

The encrypted export uses the same Fernet key derivation as individual file encryption. The passphrase is never stored anywhere. The `--backup` command (in `backup.py`) produces a single encrypted `.tar.gz` of the whole `.finance/` directory, optionally to iCloud.

## All Security Controls

```python
from scripts.data_safety import (
    get_privacy_summary,          # Full security status report
    get_data_inventory,           # Audit what's stored and where
    harden_permissions,           # chmod 600/700 on all .finance/ files
    check_permissions,            # Check for insecure file permissions
    ensure_gitignore_protection,  # Add .finance/ to .gitignore
    encrypt_sensitive_files,      # Encrypt profile, accounts, investments, debt
    decrypt_sensitive_files,      # Decrypt for use
    encrypt_file,                 # Encrypt a single file
    decrypt_file,                 # Decrypt a single file
    export_all_data,              # Export (plain or encrypted)
    import_data,                  # Import from export file
    delete_all_data,              # Permanent wipe (requires confirm=True)
    delete_category,              # Delete one category (requires confirm=True)
    sanitize_for_sharing,         # Strip PII before sharing for help
    get_access_log,               # View audit trail
)
```

## What Happens on First Session

```
skill.py (session start)
  ├── ensure_gitignore_protection()   # .finance/ → .gitignore
  ├── check_permissions()             # warn if group/world readable
  └── get_profile()                   # load or start onboarding
      └── (new user) show privacy statement
```

The privacy statement is shown once:

> *Your data lives on your machine in `.finance/` — nothing is uploaded (a few opt-in price/rate lookups send only tickers or currency codes). You can encrypt it, export it, or delete it completely at any time. I never store bank credentials, card numbers, IBANs, or government IDs.*

## Threat Model

| Threat | Protection |
|--------|-----------|
| Another user on same machine reads your files | `harden_permissions()` — chmod 600/700 |
| Accidental `git push` of financial data | `ensure_gitignore_protection()` — automatic on session start |
| Laptop stolen, unencrypted disk | `encrypt_sensitive_files(passphrase)` + OS disk encryption (FileVault/LUKS) |
| Weak passphrase undermines AES | `_check_passphrase_strength()` — enforced before every encrypt call |
| Power failure during encryption corrupts file | Atomic write via `.enc.tmp` → `rename()` — POSIX atomic |
| Sharing data for help leaks names/employer | `sanitize_for_sharing()` — redacts all PII fields |
| Unexpected data access by a process | `get_access_log()` — timestamped audit trail |
| Cloud backup of export file exposes data | `export_all_data(passphrase=...)` — Fernet-encrypted export |

## Sending zero data to Anthropic

By default Claude Code sends your prompts and file context to Anthropic's API — your **data on disk** never leaves your machine, but the **conversation** does. For fully local operation (confidential client data, sovereignty policies), route Claude Code through a local model. See [`sovereignty.md`](sovereignty.md) for the recipe and an accuracy harness that measures the tradeoff on your own hardware.

## Network calls (opt-in)

| Host | Triggered by | What is sent | What comes back |
|------|--------------|--------------|-----------------|
| `api.frankfurter.app` | exchange-rate sync (`currency.sync_exchange_rates`) | base currency code | daily FX rates |
| `query1.finance.yahoo.com` | stock price sync (`price_sync`) | ticker symbols | quotes |
| `api.coingecko.com` | crypto price sync (`price_sync`) | coin ids | quotes |
| `bankaccountdata.gocardless.com` | bank sync (`bank_sync`, needs your GoCardless credentials) | your credentials, chosen institution | account/transaction data from your bank |
| `cdn.jsdelivr.net` | opening a generated dashboard in a browser | (browser fetch of pinned, SRI-verified Chart.js) | JavaScript |

Nothing else opens a socket. Verify: `grep -rn "urlopen\|requests\." scripts/`.

## Where data lives on disk

- `.finance/` — profile, accounts, transactions (JSON + `finance.db`), budgets, goals, and `originals/` (copies of statements you imported; skipped with `keep_original=False`). "Encrypt my data" covers the JSON files, `finance.db`, `originals/`, and the GoCardless token cache; decrypt before using the skill again.
- `.finance/bank_sync/credentials.enc` — GoCardless credentials, always encrypted. `token_cache.json` holds only the short-lived (~24 h) access token.
- `~/.finance/audit.log` — change log with amounts and descriptions. Lives in your home directory (not the project), is plaintext (chmod 600), and is deleted by `delete_all_data`.

## Known Limitations

- **Memory**: Decrypted data resides in Python process memory while the skill is running. Python does not securely zero memory on deallocation. This is a fundamental Python limitation.
- **OS keychain**: Passphrases are not stored in the OS keychain (macOS Keychain, GNOME Keyring). You must provide the passphrase each session when using encrypted files. This is deliberate — no stored secret means no stored secret to steal.
- **Disk encryption**: If your disk is not encrypted (macOS FileVault, Linux LUKS), Fernet protects against OS-level access control bypass but not against forensic disk reads. Enable full-disk encryption for maximum protection.
- **Audit log**: `.finance/audit/access_log.json` holds timestamps and action types only. The separate change log `~/.finance/audit.log` does contain amounts and descriptions and is not encrypted.
