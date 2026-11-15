# X (Twitter)

- Login page: `https://x.com/home`
- Visible browser profile: `.local/social/x/profile`
- Remote debugging: `127.0.0.1:9322`

## Recognition

| State | Evidence |
| --- | --- |
| `login-required` | `accounts.google.com`, `/i/flow/login`, `input[name="text"]`, `Entrar`/`Sign in` |
| `challenge` | `/account/access` or challenge marker in the URL |
| `logged-in` | `[data-testid="SideNav_AccountSwitcher_Button"]` with `@handle`, or `a[data-testid="AppTabBar_Profile_Link"]` |
| `unknown` | none of the above; nothing is saved |

The account record is `.local/social/x/account.json` with mode 0600. It stores only the
handle, display name, state and verification time. The session itself stays in the Chrome
profile, which is private and ignored by Git.

```bash
python3 -m tools.ytbot social open --network x
python3 -m tools.ytbot social status --network x
```

If X shows a Google account chooser or a challenge, finish it manually in the visible
window and rerun `status`. The bot never automates credentials, two-factor or challenges.
