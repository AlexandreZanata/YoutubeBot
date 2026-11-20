# Session contract — no silent crash on a signed-out profile

An expired YouTube/Google session is an **owner action**, not a retryable bug. Every entry
point that touches a browser profile follows the same contract.

## Invariant

Before any interaction with a channel page (avatar menu, upload dialog, comments inbox,
community post), the bot checks whether the page is the signed-out screen. If it is:

1. Stop the hidden browser for that profile.
2. Record `.local/ytbot/needs-login.json` with the profile, URL, reason and timestamp.
3. Open a visible window on the sign-in page for the owner.
4. Raise `UploadBlocked` / `RuntimeError` with the message
   “YouTube session expired; finish the sign-in in the window that opened”.
5. Do not retry, loop, bypass or copy another profile.

The owner completes the login (and any two-step verification) by hand. The marker clears on the
next successful channel check for that profile.

## Where it is enforced

- `upload_guard.login_required(body)`: single source of truth for the signed-out/challenge
  markers (login, sign-in, identity verification).
- `upload_guard.page_blocked(page)`: used by the upload dialog.
- `account.ensure_channel`: checks the page with `login_required` **before** waiting for or
  clicking `#avatar-btn`; a missing avatar without a login marker also stops with
  `UploadBlocked` instead of a Playwright timeout.
- `chat.ensure_logged_in`: same idea for ChatGPT.
- `tests/test_session_contract.py` locks the recognition list and the ordering (detection
  before the avatar click).

## Regression this fixed (2026-11-19)

The Fallem Prince legacy profile lost its YouTube session while keeping the ChatGPT session.
`ensure_channel` clicked `#avatar-btn` blindly and died with a 30 s Playwright timeout; two
Shorts were reported as “channel failures” with no actionable message and no login window.
The check now recognises the sign-out screen, opens the window once and fails fast with the
reason. The Fallem queue stops until the owner logs in; no upload is ever attempted signed out.

## Rules for new automation

- Never call `#avatar-btn`, the upload dialog or a channel page without the login check.
- Never treat a signed-out page as a media or navigation error.
- Never open a visible window for an idle profile; only for a real expired/challenge page.
- CI covers this with text fixtures; no live account is touched.
