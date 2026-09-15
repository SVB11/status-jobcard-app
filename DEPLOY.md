# How to update Status Job Cards without losing data

Live site: https://www.stsjobcards.co.za

## One-time Railway setup
1. Service → Volumes → add volume, mount path `/data`
2. Service → Variables → `SQLITE_PATH` = `/data/status_jobcard.db`
3. After the first jobs exist, Admin dashboard → Download database backup
4. Save that `.db` on the office PC

## Every update from Grok
1. Unzip the new folder
2. Copy code files into GitHub Desktop repo
3. NEVER upload `status_jobcard.db`
4. Commit and Push
5. Wait for Railway Active
6. Log in with the SAME passwords
7. Admin → Download database backup again

## If jobs disappear
Use the last `.db` backup from the office PC. Do not create a new empty volume.
