# Instagram

- Login page: `https://www.instagram.com/accounts/login/`
- Home check: `https://www.instagram.com/`
- Visible browser profile: `.local/social/instagram/profile`
- Remote debugging: `127.0.0.1:9323`
- Hidden Xvfb display: `:91`

## Recognition

| State | Evidence |
| --- | --- |
| `login-required` | `/accounts/login`, username input, or `Entrar`/`Log in` button or link |
| `challenge` | `/challenge/` or `/checkpoint/` |
| `logged-in` | home/direct marker plus a profile avatar alt or profile link |
| `unknown` | none of the above; nothing is saved |

The account record is `.local/social/instagram/account.json` with mode 0600. It stores only
the handle, display name when available, state and verification time. The session stays in the
Chrome profile, which is private and ignored by Git.

```bash
python3 -m tools.ytbot social open --network instagram
python3 -m tools.ytbot social status --network instagram
python3 -m tools.ytbot social stop --network instagram
```

`open` shows a visible Chrome window for login and challenges. `status` and `stop` use the
hidden Xvfb runtime on display `:91`, following the same rule as X and the YouTube runtime.

## Current scope

Session and account recognition only. Publishing, discovery and contextual replies are not
implemented for Instagram yet. Do not reuse the X publishing or discovery commands for this
network.
