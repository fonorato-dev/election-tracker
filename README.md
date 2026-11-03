# Election night race tracker

A free, self-updating, password-protected website. No Claude, no API keys, no paid services.

- **GitHub Actions** runs `scripts/update.py` every ~10 minutes. It pulls Google News headlines for each watch-list candidate. **Only stories published by the Associated Press itself (apnews.com) can change a race's status automatically**; other outlets citing AP are ignored, as are primary/runoff/nomination stories, hedged headlines ("leads", "expected") and anything published before that race's polls closed. Automatic calls show in amber as "verify"; anyone can still mark a race with the status dropdown.
- **GitHub Pages** serves `index.html`. After the password is entered, the page re-reads the data every 60 seconds, so an open tab updates itself.
- **Password protection:** the watch list, headlines and calls are stored encrypted (AES-256) in `data/source.enc` and `data/site.enc`. The page decrypts them in the browser only with the right password, so the repo and site show nothing readable without it.

## One-time setup

1. **Add the password as a secret:** Settings > Secrets and variables > Actions > New repository secret.
   Name: `TRACKER_PASSWORD`. Value: the password you were given.
2. **Allow the workflow to save data:** Settings > Actions > General > Workflow permissions > **Read and write permissions** > Save.
3. **Turn on the website:** Settings > Pages > Source **Deploy from a branch**, Branch `main`, folder `/ (root)` > Save.
   The site appears at `https://<username>.github.io/election-tracker/` within a couple of minutes.
4. **Start it:** Actions tab > **Update race data** > **Run workflow**. After that it runs on its own.

## Confirming or correcting a call

**Easiest: the dropdown under each race's status** (Automatic / Not called / AP called: candidate).
It updates that screen instantly. To make it show for everyone, click **Sharing: off** at the top once and
paste a fine-grained GitHub token (Only select repositories → election-tracker; Contents: Read and write;
7-day expiry). The token stays in that browser only. With sharing on, each pick is saved to
`data/overrides.json` and appears for everyone in about 2 minutes.

**Or by hand:**

Automatic flags come from headline matching, so amber means "AP headline spotted, verify".
To confirm a call (turns green) or fix a race, edit `data/overrides.json` in the GitHub web editor:

```json
{
  "GA-SEN": {"status": "Called", "winner": "Jon Ossoff (D)", "called_at_et": "8:12 PM",
             "line": "AP just called the Georgia Senate race: Jon Ossoff (D) wins, defeating Mike Collins (R)."},
  "MI-07":  {"status": "Not called"}
}
```

Saving that file triggers an update right away; the site shows it within about 2 minutes.
Note: `overrides.json` is **not** encrypted, so anything typed there is visible in the public repo. Race calls are public information anyway; just don't add private notes there.

## Changing the password or the race list

Requires Python and `pip install cryptography`:

```
python scripts/manage.py rotate OLD_PASSWORD NEW_PASSWORD       # then update the TRACKER_PASSWORD secret
python scripts/manage.py export PASSWORD > source.json          # decrypt the race list to edit
python scripts/manage.py import PASSWORD source.json            # re-encrypt it (never commit source.json)
```

Commit the updated `data/source.enc`, then run the workflow.

## Notes

- GitHub's scheduler can run a few minutes late at busy times, and election night is busy.
- Official AP calls come from AP's paid Elections API, so this watches news headlines instead.
  For the fastest calls, keep AP's live results page open next to the tracker.
- "Remember on this device" keeps the password in that browser; the Lock button clears it.
- After election week, disable the workflow: Actions > Update race data > "..." > Disable workflow.
