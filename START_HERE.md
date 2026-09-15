# Status Job Cards — clean start

Site: https://www.stsjobcards.co.za

## Included
- Sales / Workshop / Admin / Accounts logins
- Job cards, PDI, parts, 3rd parties, extras approval
- Roadworthy pass/fail on the same task
- Diary from Work/Prep tasks
- Creator can correct WS + vehicle details
- Dark theme
- Admin full backup zip (database + jobs + parts)

## Railway (do once)
Volume mount: /data
Variable: SQLITE_PATH=/data/status_jobcard.db

## Every code update
Copy code only. Never upload status_jobcard.db. Never delete the volume.
After go-live: Admin → DOWNLOAD FULL BACKUP (ZIP) to the office PC.
