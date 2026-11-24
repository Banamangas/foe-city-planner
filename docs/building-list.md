# Building list (daily update)

A GitHub job reads the game's building data from your API once a day. It builds
a small list of buildings and publishes it as two files on the GitHub release
named "catalog". The app downloads those two files to learn new buildings. The
big game export is never stored on GitHub.

If the game data has not changed since the last run, the job stops and does nothing.

## One-time setup

1. In your API, create a new key that can only read. Use it only for this job.
2. In the repository on GitHub, go to Settings -> Secrets and variables -> Actions.
   Click "New repository secret". Name it `FOE_API_KEY` and paste the key as the value.

## Run it by hand

1. Go to the Actions tab of the repository.
2. Click "Building list" in the left column.
3. Click "Run workflow". Tick "force" if you want a rebuild even when nothing changed.

## Check that it worked

1. Open the repository's Releases page and find the release "Building list" (tag `catalog`).
2. Its assets `catalog.json.gz` and `catalog-manifest.json` should show a fresh date.
3. If the run turned red, open it in the Actions tab and read the failing step.
   A message "API update failed" means your API's own last update failed; nothing was published.
