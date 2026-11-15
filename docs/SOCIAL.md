# Social promotion

The promotion module publishes the owner's GitHub projects on social networks. Post copy is
Brazilian Portuguese; code, comments and this documentation stay in English. Each network
has its own code folder and its own private browser profile:

```
tools/ytbot/social/
  store.py          private per-network folders and account records
  browser.py        visible Chrome, one profile and one CDP port per network
  commands.py       social open/status CLI
  x/                X (Twitter) login detection
```

```
.local/social/
  x/profile/        persistent Chrome session, never in Git
  x/account.json    0600 record with handle, display name and verification time
  x/browser.pid     0600 process record
```

The shared YouTube profile is never reused. The social browser opens in the owner's
graphical session, so sign-in and any challenge stay visible and manual.

## Connect X

```bash
python3 -m tools.ytbot social open --network x
```

The command starts Chrome with `--user-data-dir=.local/social/x/profile` and remote debugging
on `127.0.0.1:9322`, then opens `https://x.com/home`. The wait for the debug port is bounded
to 30 seconds. The owner signs in normally, including password, two-factor authentication,
Google sign-in or any X challenge. The command never reads or prints the password.

```bash
python3 -m tools.ytbot social status --network x
```

The status command attaches to the same browser context and runs the recognition steps:

1. Open `https://x.com/home` and wait for the client to render.
2. If the URL is `accounts.google.com` or `/i/flow/login`, a login form is present, or the
   page offers `Entrar`/`Sign in`, report `login-required`.
3. If the URL contains `/account/access` or a challenge marker, report `challenge`.
4. If `[data-testid="SideNav_AccountSwitcher_Button"]` is present, parse `@handle` and the
   display name from its text.
5. Otherwise use `a[data-testid="AppTabBar_Profile_Link"]` and parse the handle from its
   path.
6. On `logged-in`, write only `network`, `state`, `handle`, `display_name` and
   `verified_at` to `.local/social/x/account.json` with mode 0600. Cookies, tokens,
   passwords and page HTML are never saved in the record, logs or Git.

Any other result is `unknown` and is not saved. The bot does not click through login,
two-factor or challenge screens. Rerun `status` after finishing them in the visible window.

## Network folders

Add the next network as a sibling package, for example `social/instagram/`, with its own
login URL, CDP port, selectors and README. Keep one private `.local/social/<network>/`
folder per network. Do not share a Chrome profile between networks.

## Operational rules

- Require an explicit network; never guess the account.
- Keep promotion copy in Brazilian Portuguese and focus on the GitHub project.
- Do not publish, follow, reply or change a profile until the owner gives explicit copy
  and action instructions.
- Never put session cookies, tokens, screenshots with account data or private paths in Git.
- A closed browser or an expired session returns to `login-required`; the owner signs in
  again in the visible window.
