this is meant to explain what the rewrite of the deploy_heroku.py script did
if these benefits do not manifest something is wrong (i hope not)

## impt
the main niceties brought about
- heroku-26 is now being used, so far it doesn't *seem* to have changed anything for the worse
  - at least for myself heroku wouldn't let me deploy tabbycat while using the 22 stack which is why i even started the fork in the first place
- proper waiters for postgres and redis being used
  - currently, the upstream script uses an infinite polling loop that doesn't have error handling or timeouts (the problem here is that if something goes bad during building/deployment the script loops forever and you wouldn't know) 
- dry-run now LARPs instead of making an app and leaving you with the bill
  - when set, it just returns an empty string before it ever calls a subprocess

you can drop this in and it'll work just fine
## not impt
these aren't as consequential, but would probably be nice
- django doesn't print it's secret in the CLI
- heroku auth:whoami is used to check if you have heroku CLI installed
  - previously ~~on DBZ~~ the script finds out when it commits to deploying, imo the better option is just to check from the start instead
- error codes are printed so you can look them up
- removed rotting conditional `if args.time_zone`
  - default was never `None` so it was always true
- if deployment URL can't be opened on the browser, script doesn't abort
## notable
these are things i either haven't checked or inconveniences as a result of the rewrite
- needs python 3.6+ now instead of just python 2.7+ because of `import secrets`
  - also using os instead of platform so there's that
- this works on non-windows systems in theorem, but whether it actually does isn't verified