# SkillProof — functional full-stack prototype

This version is intentionally more than a static mockup. It includes:

- persistent SQLite database
- real registration and login sessions
- student and business roles
- businesses can publish projects
- students can search and apply
- businesses can accept/reject applications
- students can submit a real portfolio/file URL
- businesses can review and verify the work
- verified projects appear in the student's portfolio
- venture feedback is saved to the database

## Run locally

No third-party Python packages are required.

```bash
python app.py
```

Open: http://127.0.0.1:8000

Demo accounts:

- Student: `student@skillproof.demo` / `demo123`
- Business: `business@skillproof.demo` / `demo123`

## Deploy

The app reads the hosting platform's `PORT` environment variable and binds to `0.0.0.0`, so it can be deployed to a Python-capable host such as Render, Railway, Fly.io, or a VPS.

Start command:

```bash
python app.py
```

Important: the included SQLite database is suitable for a prototype. For a real public launch, migrate to PostgreSQL and add production-grade email verification, rate limiting, CSRF protection, file storage, moderation, privacy controls, legal terms, and a real payment provider.
