# Computer: logins and takeover

> Written before `docs/computer.md` (the user guide, PR 8) exists on this branch. Fold this in as a "Logins and takeover" section there once it does.

The helper never types a password, a 2FA code or a CAPTCHA answer, and never asks you for one. When a page needs you in person it calls `request_takeover(reason)` and waits.

**What you see.** A message from the agent in the chat the task came from (Telegram, WhatsApp or the web), or on every notification channel for background tasks: why the helper stopped, which agent it works for, and a link to the screen: `/computer?task=<id>&agent=<slug>`. On Telegram the link is also a button when Chatty is served over https.

**What you do.** Open the link (it asks for your Chatty login first), read the reason line at the top, press **Take control**, do the sign-in on the screen, then press **I'm done — hand back to the helper**. The helper sees nothing you type: while you have control every agent call to the computer is refused, including screenshots and page reads. The cookies stay in that agent's Chrome profile, so the next task is already signed in.

**What the helper does.** It holds the screen for up to 15 minutes waiting for you to take control (the task's clock stops meanwhile). If nobody comes, the task ends with the reason "sign-in needed" and the agent tells you how to finish it yourself. Once you hand back, the helper takes a fresh look at the page and continues. Your takeover itself can last up to 15 minutes; if your phone drops off, the computer keeps the session for 60 seconds and then hands back on its own.

**Also**

- Cancelling the task (card or chat) during either wait ends it.
- "Take control" from the Computer card with no task running works the same way; a task that arrives meanwhile waits for your handback instead of failing.
- The task's `takeover_state` on the card and the task API is `waiting` (asked, nobody has the screen yet), `active` (a person has the screen) or empty.
