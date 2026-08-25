# Status Truck Sales – Job Card & Workshop System

Mobile-friendly web app connecting Sales and Workshop for vehicle preparation after a sale.

## Features

- Individual staff logins (Sales, Workshop, Accounts, Admin)
- Create Job Cards with vehicle details (WS####) and type-specific tasks
- Workshop Accept → update task statuses → add notes / extra tasks
- Digital PDI checklists (Truck / Tanker / Trailer & Tipper)
- Dual signatures for PDI and Ready for Delivery
- Admin user management
- Full audit trail
- Company logo on all screens

## Local Run (testing on your computer)

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open: http://localhost:8000

## Default Logins

| Role     | Username   | Password    |
|----------|------------|-------------|
| Admin    | admin      | admin123    |
| Sales    | sales1     | sales123    |
| Workshop | workshop1  | workshop123 |
| Accounts | accounts   | accounts123 |

Change these passwords immediately after going live.

## Deploying Online (Railway)

1. Create a free account at https://railway.app
2. Create a new project → Deploy from local folder / GitHub
3. Railway will detect the Procfile and requirements.txt
4. Set environment variables (recommended):
   - SECRET_KEY = a long random string
5. Railway gives you a public URL automatically

## Custom Domain

After the app is live on Railway:

1. Buy a domain (recommended: .co.za)
2. In Railway → Settings → Domains → Add custom domain
3. Point your domain’s DNS (CNAME or A record) to Railway as instructed
4. Staff then open e.g. https://jobs.yourdomain.co.za

Suggested domain names:
- jobs.statustruck.co.za
- workshop.statustruck.co.za
- jobcards.statustruck.co.za

## Important Notes

- Change all default passwords once live
- SQLite is fine for a small team; can upgrade to PostgreSQL later if needed
- Take occasional backups of the database file
